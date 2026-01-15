#!/usr/bin/env python
import os
import asyncio
import re
import traceback
from datetime import datetime, timezone
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.svm import SVC
from joblib import dump
from sqlalchemy import func, or_, and_

import src.helpers.db_helper as db_helper
import src.helpers.logging_helper as logging_helper
import src.helpers.rating_helper as rating_helper  # assumed to have get_rating(user_id, chat_id)

logger = logging_helper.get_logger()

def extract_raw_features(raw_msg):
    """
    From the raw_message JSON (a dict) extract:
      - custom_emoji_count: count of objects in raw_msg["entities"] that have a "custom_emoji_id"
      - raw_text_length: length of the raw message's "text" field (if exists) else 0.
      - raw_chat_id: if raw_msg contains a "chat" object with an "id", use that; else 0.
    """
    custom_emoji_count = 0
    raw_text_length = 0
    raw_chat_id = 0
    if isinstance(raw_msg, dict):
        entities = raw_msg.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict) and "custom_emoji_id" in entity:
                    custom_emoji_count += 1
        text = raw_msg.get("text")
        if isinstance(text, str):
            raw_text_length = len(text)
        chat_obj = raw_msg.get("chat")
        if isinstance(chat_obj, dict):
            raw_chat_id = chat_obj.get("id", 0)
    return custom_emoji_count, raw_text_length, raw_chat_id

def extract_user_name_lengths(user_raw, fallback_first_name, fallback_last_name):
    """
    From the raw JSON stored in User.user_raw (if available) extract the lengths of first and last names.
    If not available, fall back to the provided fallback values.
    """
    first_name = fallback_first_name
    last_name = fallback_last_name
    if isinstance(user_raw, dict):
        first_name = user_raw.get("first_name") or fallback_first_name
        last_name = user_raw.get("last_name") or fallback_last_name
    first_name_len = len(first_name) if isinstance(first_name, str) else 0
    last_name_len = len(last_name) if isinstance(last_name, str) else 0
    return first_name_len, last_name_len

async def train_spam_classifier_raw():
    """
    Train an SVM spam classifier using features derived from the stored embedding,
    plus raw JSON data and user information. Only messages satisfying at least one of:
       - manually_verified = true, or
       - spam_prediction_probability > 0.99 and is_spam = true, or
       - spam_prediction_probability < 0.01 and is_spam = false
    are used.
    
    For each message, the feature vector is constructed by concatenating:
      1. The embedding vector (from Message_Log.embedding)
      2. custom_emoji_count (number of objects in raw_message.entities with "custom_emoji_id")
      3. raw_text_length (length of raw_message.text)
      4. delta_time (in seconds between now and User.created_at)
      5. user_rating (obtained via rating_helper.get_rating(user_id, chat_id))
      6. user_first_name_length (from User.user_raw if available, else User.first_name)
      7. user_last_name_length (from User.user_raw if available, else User.last_name)
      8. raw_chat_id (from raw_message.chat.id; if not present, 0)
      
    During evaluation the script prints the mis‐classified samples along with these non‐embedding features,
    the raw message text, and the predicted probability.
    """
    try:
        with db_helper.session_scope() as session:
            logger.info("Fetching messages from the database for raw training...")
            query = (session.query(
                        db_helper.Message_Log.id,
                        db_helper.Message_Log.embedding,
                        db_helper.Message_Log.raw_message,
                        db_helper.Message_Log.is_spam,
                        db_helper.Message_Log.user_id,
                        db_helper.Message_Log.chat_id,
                        db_helper.Message_Log.message_timestamp,
                        db_helper.Message_Log.spam_prediction_probability,
                        db_helper.User.created_at.label("user_created_at"),
                        db_helper.User.first_name,
                        db_helper.User.last_name,
                        db_helper.User.user_raw
                    )
                    .join(db_helper.User, db_helper.User.id == db_helper.Message_Log.user_id)
                    .filter(
                        db_helper.Message_Log.embedding != None,
                        db_helper.Message_Log.raw_message != None,
                        or_(
                            db_helper.Message_Log.manually_verified == True,
                            and_(db_helper.Message_Log.spam_prediction_probability > 0.98, db_helper.Message_Log.is_spam == True),
                            and_(db_helper.Message_Log.spam_prediction_probability < 0.02, db_helper.Message_Log.is_spam == False)
                        )
                    )
                    .order_by(db_helper.Message_Log.id.desc())
            )
            messages_data = query.all()
            logger.info(f"Fetched {len(messages_data)} messages.")
            if not messages_data:
                logger.info("No messages to process.")
                return None

            features = []
            labels = []
            raw_info_list = []  # This will store non-embedding features and raw text for evaluation

            logger.info("Processing messages data for feature extraction...")
            for msg in messages_data:
                # Compute delta time (in seconds) from now and when the user registered.
                delta_time = (datetime.now(timezone.utc) - msg.user_created_at).total_seconds()
                
                # Extract raw JSON features: custom_emoji_count, raw_text_length, raw_chat_id.
                custom_emoji_count, raw_text_length, raw_chat_id = extract_raw_features(msg.raw_message)
                
                # Extract user name lengths from user_raw (if available) or fallback.
                user_first_name_len, user_last_name_len = extract_user_name_lengths(msg.user_raw, msg.first_name, msg.last_name)
                
                # Obtain the user rating.
                user_rating_value = rating_helper.get_rating(msg.user_id, msg.chat_id)
                
                # Build the feature vector by concatenating:
                # [embedding, custom_emoji_count, raw_text_length, delta_time, user_rating,
                #  user_first_name_len, user_last_name_len, raw_chat_id]
                try:
                    feature_vector = np.concatenate((
                        msg.embedding,
                        np.array([
                            float(custom_emoji_count),
                            float(raw_text_length),
                            float(delta_time),
                            float(user_rating_value),
                            float(user_first_name_len),
                            float(user_last_name_len),
                            float(raw_chat_id)
                        ])
                    ))
                except Exception as concat_err:
                    logger.error(f"Error concatenating features for message_id {msg.id}: {concat_err}")
                    continue

                features.append(feature_vector)
                labels.append(msg.is_spam)
                
                # Prepare raw information (excluding the embedding) for later inspection.
                non_embedding_features = {
                    "custom_emoji_count": custom_emoji_count,
                    "raw_text_length": raw_text_length,
                    "delta_time": delta_time,
                    "user_rating": user_rating_value,
                    "user_first_name_len": user_first_name_len,
                    "user_last_name_len": user_last_name_len,
                    "raw_chat_id": raw_chat_id
                }
                raw_text = None
                if isinstance(msg.raw_message, dict):
                    raw_text = msg.raw_message.get("text")
                raw_info_list.append({
                    "message_id": msg.id,
                    "raw_text": raw_text,
                    "non_embedding_features": non_embedding_features
                })
            
            logger.info("Feature extraction complete.")
            if not features:
                logger.info("No features to train on.")
                return None

            features = np.array(features)
            labels = np.array(labels)

            imputer = SimpleImputer(strategy='mean')
            features = imputer.fit_transform(features)

            unique_classes, class_counts = np.unique(labels, return_counts=True)
            logger.info(f"Class distribution: {dict(zip(unique_classes, class_counts))}")

            # Set test size fraction (e.g. 10% of the data)
            test_size_fraction = 0.1  

            # Note: raw_info_list is used only for evaluation, so we do not need to split it
            X_train, X_test, y_train, y_test, raw_info_train, raw_info_test = train_test_split(
                features, labels, raw_info_list, test_size=test_size_fraction, stratify=labels
            )

            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train)
            X_test = scaler.transform(X_test)

            # Train an SVM classifier with an RBF kernel.
            model = SVC(kernel='rbf', probability=True, C=1.0, gamma='scale')
            model.fit(X_train, y_train)

            accuracy = model.score(X_test, y_test)
            logger.info(f"Raw model accuracy: {accuracy}")

            dump(model, 'ml_models/svm_spam_model_raw.joblib')
            dump(scaler, 'ml_models/scaler_raw.joblib')

            # Evaluate misclassified samples, printing their predicted probabilities and raw features.
            y_pred = model.predict(X_test)
            y_prob = model.predict_proba(X_test)
            logger.info("Wrongly classified messages:")
            for i in range(len(y_pred)):
                if y_pred[i] != y_test[i]:
                    info = raw_info_test[i]
                    logger.info(
                        f"Message ID: {info['message_id']}\n"
                        f"Predicted: {'Spam' if y_pred[i] else 'Not Spam'}, True: {'Spam' if y_test[i] else 'Not Spam'}\n"
                        f"Predicted Probability: {y_prob[i][1]:.4f}\n"
                        f"Raw text: {info['raw_text']}\n"
                        f"Non-embedding features: {info['non_embedding_features']}\n"
                    )
            return model
    except Exception as e:
        logger.error(f"An error occurred while training the raw spam classifier: {e}. Traceback: {traceback.format_exc()}")
        return None

if __name__ == '__main__':
    asyncio.run(train_spam_classifier_raw())
