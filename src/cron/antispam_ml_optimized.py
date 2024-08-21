import sys
import os
from datetime import datetime, timezone
sys.path.append(os.getcwd())

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
import traceback
from joblib import dump
import asyncio

import src.spamcheck_helper as spamcheck_helper
import src.db_helper as db_helper
import src.logging_helper as logging
from sqlalchemy import func

# Configure logger
logger = logging.get_logger()

async def train_spam_classifier():
    """Train a simple SVM model for spam detection using message embeddings, content, user ratings, and time difference."""
    try:
        with db_helper.session_scope() as session:
            
            logger.info("before db")
            # Fetch all necessary data in one query, limit to 1000 rows for debugging
            spam_count_subquery = (
                session.query(func.count())
                .filter(db_helper.Message_Log.user_id == db_helper.Message_Log.user_id, db_helper.Message_Log.is_spam == True)
                .correlate(db_helper.Message_Log)
                .scalar_subquery()
            )

            not_spam_count_subquery = (
                session.query(func.count())
                .filter(db_helper.Message_Log.user_id == db_helper.Message_Log.user_id, db_helper.Message_Log.is_spam == False)
                .correlate(db_helper.Message_Log)
                .scalar_subquery()
            )

            query = (
                session.query(
                    db_helper.Message_Log.id,
                    db_helper.Message_Log.embedding,
                    db_helper.Message_Log.message_content,
                    db_helper.Message_Log.user_id,
                    db_helper.Message_Log.chat_id,
                    db_helper.Message_Log.is_spam,
                    db_helper.Message_Log.user_current_rating,
                    db_helper.User_Status.created_at.label('status_created_at'),
                    db_helper.User.created_at.label('user_created_at'),
                    spam_count_subquery.label('spam_count'),
                    not_spam_count_subquery.label('not_spam_count')
                )
                .outerjoin(db_helper.User_Status, 
                    (db_helper.User_Status.user_id == db_helper.Message_Log.user_id) & 
                    (db_helper.User_Status.chat_id == db_helper.Message_Log.chat_id)
                )
                .join(db_helper.User, db_helper.User.id == db_helper.Message_Log.user_id)
                .filter(db_helper.Message_Log.embedding != None,
                        db_helper.Message_Log.message_content != None)
                # .limit(10000)
            )

            logger.info("after db")

            messages_data = query.all()

            # Log how many messages we have
            logger.info(f"Fetched {len(messages_data)} messages from the database.")

            if not messages_data:
                logger.info("No messages to process.")
                return None

            # Prepare features and labels
            features = []
            labels = []
            message_contents = {}

            logger.info("before messages_data loop")

            for message_data in messages_data:
                joined_date = message_data.status_created_at if message_data.status_created_at else message_data.user_created_at
                time_difference = (datetime.now(timezone.utc) - joined_date).days
                message_length = len(message_data.message_content)

                feature_array = np.concatenate((
                    message_data.embedding,
                    [message_data.user_current_rating, time_difference, message_data.chat_id, message_data.user_id, message_length, message_data.spam_count, message_data.not_spam_count]
                ))

                features.append(feature_array)
                labels.append(message_data.is_spam)
                message_contents[message_data.id] = message_data.message_content
                
            logger.info("after messages_data loop")

            if not features:
                logger.info("No features to train on.")
                return None

            # Convert features to a NumPy array
            features = np.array(features)

            # Log the features to inspect the data
            logger.info(f"Features array: {features}")

            # Check the dtype of the features array
            logger.info(f"Features array dtype: {features.dtype}")

            # Attempt to convert the features array to a numeric dtype
            try:
                features = features.astype(np.float64)
            except ValueError as e:
                logger.error(f"Error converting features to numeric: {e}")
                return None

            # Now that the data is numeric, check for NaN values
            nan_indices = np.isnan(features).any(axis=1)
            if np.any(nan_indices):
                logger.warning(f"Found {np.sum(nan_indices)} rows with NaN values in the features.")
                logger.warning(f"NaN values are in the following rows: {features[nan_indices]}")
            else:
                logger.info("No NaN values found before removal.")

            # Ensure nan_indices is a boolean array
            nan_indices = nan_indices.astype(bool)

            # Remove rows with NaN values
            features_clean = features[~nan_indices]
            labels_clean = np.array(labels)[~nan_indices]
            cleaned_ids = np.array(list(message_contents.keys()))[~nan_indices]

            # Log NaN values after removal to double-check
            if np.isnan(features_clean).any():
                remaining_nan_indices = np.isnan(features_clean).any(axis=1)
                logger.error(f"NaN values still present after cleaning in the following rows: {features_clean[remaining_nan_indices]}")
                return None
            else:
                logger.info("All NaN values successfully removed.")

            X_train, X_test, y_train, y_test, ids_train, ids_test = train_test_split(
                features_clean, labels_clean, cleaned_ids, test_size=0.2, random_state=42)

            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train)
            X_test = scaler.transform(X_test)

            logger.info("before SVC")
            model = SVC(kernel='linear', probability=True)
            logger.info("before fit")
            model.fit(X_train, y_train)
            logger.info("before score")
            accuracy = model.score(X_test, y_test)
            logger.info(f"🎉Model accuracy: {accuracy}")

            # Dump the trained model and scaler to file
            logger.info("before dump")
            dump(model, 'ml_models/svm_spam_model.joblib')
            dump(scaler, 'ml_models/scaler.joblib')

            logger.info("before predict")
            # Evaluate wrongly classified messages
            y_pred = model.predict(X_test)
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