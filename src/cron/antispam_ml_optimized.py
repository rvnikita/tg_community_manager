import sys
import os
sys.path.append(os.getcwd())

from dotenv import load_dotenv
load_dotenv("config/.env")

from datetime import datetime, timezone
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from xgboost import XGBClassifier
import traceback
from joblib import dump
import asyncio
import re
import time
import psutil

import src.helpers.db_helper as db_helper
import src.helpers.logging_helper as logging_helper
from sqlalchemy import func, or_, and_, case

logger = logging_helper.get_logger()

def log_memory():
    """Log current memory usage"""
    process = psutil.Process()
    mem_info = process.memory_info()
    logger.info(f"Memory usage: RSS={mem_info.rss / 1024 / 1024:.1f}MB, VMS={mem_info.vms / 1024 / 1024:.1f}MB")

async def train_spam_classifier():
    """Train a spam classifier using XGBoost on message embeddings and additional features.
    This version learns from messages that are either manually verified
    or have extreme spam prediction probabilities (very high or very low).
    """
    try:
        with db_helper.session_scope() as session:
            log_memory()
            logger.info("Fetching messages from the database for training...")

            # Create a subquery to pre-aggregate spam counts per user
            # This is MUCH faster than window functions on large datasets
            spam_counts_subquery = (
                session.query(
                    db_helper.Message_Log.user_id,
                    func.sum(case((db_helper.Message_Log.is_spam == True, 1), else_=0)).label('spam_count'),
                    func.sum(case((db_helper.Message_Log.is_spam == False, 1), else_=0)).label('not_spam_count')
                )
                .group_by(db_helper.Message_Log.user_id)
                .subquery()
            )

            start_time = time.time()
            query = (session.query(
                        db_helper.Message_Log.id,
                        db_helper.Message_Log.embedding,
                        db_helper.Message_Log.image_description_embedding,
                        db_helper.Message_Log.message_content,
                        db_helper.Message_Log.user_id,
                        db_helper.Message_Log.chat_id,
                        db_helper.Message_Log.is_spam,
                        db_helper.Message_Log.user_current_rating,
                        db_helper.Message_Log.is_forwarded,
                        db_helper.Message_Log.reply_to_message_id,
                        db_helper.Message_Log.created_at.label('message_created_at'),
                        # New spam detection features
                        db_helper.Message_Log.has_video,
                        db_helper.Message_Log.has_document,
                        db_helper.Message_Log.has_photo,
                        db_helper.Message_Log.forwarded_from_channel,
                        db_helper.Message_Log.has_link,
                        db_helper.Message_Log.entity_count,
                        db_helper.User_Status.created_at.label('status_created_at'),
                        db_helper.User.created_at.label('user_created_at'),
                        db_helper.User.username.label('user_username'),
                        func.coalesce(spam_counts_subquery.c.spam_count, 0).label('spam_count'),
                        func.coalesce(spam_counts_subquery.c.not_spam_count, 0).label('not_spam_count')
                    )
                    .outerjoin(db_helper.User_Status,
                               (db_helper.User_Status.user_id == db_helper.Message_Log.user_id) &
                               (db_helper.User_Status.chat_id == db_helper.Message_Log.chat_id))
                    .join(db_helper.User, db_helper.User.id == db_helper.Message_Log.user_id)
                    .outerjoin(spam_counts_subquery, spam_counts_subquery.c.user_id == db_helper.Message_Log.user_id)
                    .filter(
                        db_helper.Message_Log.embedding != None,
                        db_helper.Message_Log.message_content != None,
                        db_helper.Message_Log.is_spam != None,  # Exclude NULL (unknown) - only use True/False
                        or_(
                            # db_helper.Message_Log.manually_verified == True,
                            and_(db_helper.Message_Log.spam_prediction_probability > 0.99, db_helper.Message_Log.is_spam == True),
                            and_(db_helper.Message_Log.spam_prediction_probability < 0.01, db_helper.Message_Log.is_spam == False)
                        )
                    )
                    .order_by(db_helper.Message_Log.id.desc())
            )
            messages_data = query.all()
            query_time = time.time() - start_time
            logger.info(f"Fetched {len(messages_data)} messages in {query_time:.2f} seconds.")
            log_memory()
            if not messages_data:
                logger.info("No messages to process.")
                return None

            features = []
            labels = []
            message_contents = {}

            logger.info("Processing messages data for feature extraction...")
            feature_start_time = time.time()

            # Get embedding dimension from first message with embedding
            embedding_dim = len(messages_data[0].embedding) if messages_data else 1536
            zero_embedding = np.zeros(embedding_dim)

            # Helper to convert None to np.nan (XGBoost handles NaN natively)
            def to_float_or_nan(val):
                return float(val) if val is not None else np.nan

            for message_data in messages_data:
                # Use the status creation time if available, otherwise use the user creation time.
                joined_date = message_data.status_created_at if message_data.status_created_at else message_data.user_created_at
                # Now compute the time difference in seconds
                time_difference = (datetime.now(timezone.utc) - joined_date).total_seconds()
                message_length = len(message_data.message_content)
                # New feature: check if the message contains a Telegram username (e.g. @rvnikita)
                has_telegram_nick = 1.0 if re.search(r'@\w+', message_data.message_content) else 0.0

                # Use image embedding if available, otherwise use zero vector
                # This allows the model to learn patterns from image content when present
                image_embedding = message_data.image_description_embedding if message_data.image_description_embedding is not None else zero_embedding
                has_image = 1.0 if message_data.image_description_embedding is not None else 0.0

                # New features: user has username, is_reply (binary), hour and day of week
                has_username = 1.0 if message_data.user_username else 0.0
                is_reply = 1.0 if message_data.reply_to_message_id else 0.0

                # Extract time features from message timestamp (UTC)
                msg_time = message_data.message_created_at
                if msg_time.tzinfo is None:
                    msg_time = msg_time.replace(tzinfo=timezone.utc)
                hour_utc = float(msg_time.hour)
                day_of_week = float(msg_time.weekday())  # 0=Monday, 6=Sunday

                feature_array = np.concatenate((
                    message_data.embedding,
                    image_embedding,
                    [
                        message_data.user_current_rating,
                        time_difference,
                        message_data.chat_id,  # KEPT: Different chats have different spam patterns/norms
                        np.log10(message_data.user_id),  # Proxy for account age: higher ID = newer account = more likely spam
                        message_length,
                        message_data.spam_count,
                        message_data.not_spam_count,
                        float(message_data.is_forwarded or 0),
                        is_reply,  # Changed from raw ID to binary (0/1)
                        has_telegram_nick,
                        has_image,
                        has_username,  # New: user has username in profile
                        hour_utc,      # New: hour of day (UTC)
                        day_of_week,   # New: day of week (0=Monday)
                        # New spam detection features (None -> np.nan for XGBoost)
                        to_float_or_nan(message_data.has_video),
                        to_float_or_nan(message_data.has_document),
                        to_float_or_nan(message_data.has_photo),
                        to_float_or_nan(message_data.forwarded_from_channel),
                        to_float_or_nan(message_data.has_link),
                        to_float_or_nan(message_data.entity_count)
                    ]
                ))
                features.append(feature_array)
                labels.append(message_data.is_spam)
                message_contents[message_data.id] = message_data.message_content

            feature_time = time.time() - feature_start_time
            logger.info(f"Completed processing messages data in {feature_time:.2f} seconds.")
            log_memory()
            if not features:
                logger.info("No features to train on.")
                return None

            logger.info("Converting features to numpy array...")
            features = np.array(features)
            labels = np.array(labels)
            logger.info(f"Features array shape: {features.shape}")
            log_memory()

            logger.info("Applying imputer...")
            imputer = SimpleImputer(strategy='mean')
            features = imputer.fit_transform(features)
            log_memory()

            unique_classes, class_counts = np.unique(labels, return_counts=True)
            logger.info(f"Class distribution before splitting: {dict(zip(unique_classes, class_counts))}")

            logger.info("Splitting train/test data...")
            X_train, X_test, y_train, y_test, ids_train, ids_test = train_test_split(
                features, labels, list(message_contents.keys()), test_size=0.2, stratify=labels, random_state=42
            )
            log_memory()

            unique_train_classes, train_class_counts = np.unique(y_train, return_counts=True)
            unique_test_classes, test_class_counts = np.unique(y_test, return_counts=True)
            logger.info(f"Training class distribution: {dict(zip(unique_train_classes, train_class_counts))}")
            logger.info(f"Test class distribution: {dict(zip(unique_test_classes, test_class_counts))}")

            logger.info("Scaling features...")
            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train)
            X_test = scaler.transform(X_test)
            log_memory()

            logger.info("Training XGBoost model...")
            train_start_time = time.time()
            model = XGBClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                n_jobs=-1,
                random_state=42,
                eval_metric='logloss'
            )
            model.fit(X_train, y_train)
            train_time = time.time() - train_start_time

            accuracy = model.score(X_test, y_test)
            logger.info(f"Model training completed in {train_time:.2f} seconds. Accuracy: {accuracy}")

            dump(model, 'ml_models/xgb_spam_model.joblib')
            dump(scaler, 'ml_models/scaler.joblib')

            y_pred = model.predict(X_test)
            logger.info("Wrongly classified messages:")
            for i in range(len(y_pred)):
                message_id = ids_test[i]
                pred = y_pred[i]
                true = y_test[i]
                content = message_contents[message_id]
                if pred != true:
                    logger.info(f"Message ID: {message_id}\nContent: {content}\nPredicted: {'Spam' if pred else 'Not Spam'}, True: {'Spam' if true else 'Not Spam'}")
            return model
    except Exception as e:
        logger.error(f"An error occurred while training the spam classifier: {e}. Traceback: {traceback.format_exc()}")
        return None

if __name__ == '__main__':
    asyncio.run(train_spam_classifier())
