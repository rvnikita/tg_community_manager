import sys
import os
from datetime import datetime, timezone
sys.path.append(os.getcwd())

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
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
            
            # Fetch the first 500 messages ordered by ID in descending order
            query = (
                session.query(
                    db_helper.Message_Log.id,
                    db_helper.Message_Log.embedding,
                    db_helper.Message_Log.message_content,
                    db_helper.Message_Log.user_id,
                    db_helper.Message_Log.chat_id,
                    db_helper.Message_Log.is_spam,
                    db_helper.Message_Log.user_current_rating,
                    db_helper.Message_Log.forwarded_message_id,  # New column
                    db_helper.Message_Log.forwarded_chat_id,  # New column
                    db_helper.Message_Log.forwarded_message_content,  # New column
                    db_helper.User_Status.created_at.label('status_created_at'),
                    db_helper.User.created_at.label('user_created_at'),
                    func.count(db_helper.Message_Log.is_spam).over(
                        partition_by=[db_helper.Message_Log.user_id],
                        order_by=db_helper.Message_Log.user_id
                    ).label('spam_count'),
                    func.count(db_helper.Message_Log.is_spam).over(
                        partition_by=[db_helper.Message_Log.user_id],
                        order_by=db_helper.Message_Log.user_id
                    ).label('not_spam_count')
                )
                .outerjoin(db_helper.User_Status, 
                    (db_helper.User_Status.user_id == db_helper.Message_Log.user_id) & 
                    (db_helper.User_Status.chat_id == db_helper.Message_Log.chat_id)
                )
                .join(db_helper.User, db_helper.User.id == db_helper.Message_Log.user_id)
                .filter(db_helper.Message_Log.embedding != None,
                        db_helper.Message_Log.message_content != None,
                        db_helper.Message_Log.manually_verified == True)  # Only use manually verified messages
                .order_by(db_helper.Message_Log.id.desc())  # Order by ID descending
                # .limit(500)  # Limit to the first 500 messages
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

                # Feature array construction including all features used in generate_features
                feature_array = np.concatenate((
                    message_data.embedding,
                    [
                        message_data.user_current_rating, 
                        time_difference, 
                        message_data.chat_id,  # Include chat_id
                        message_data.user_id,  # Include user_id
                        message_length, 
                        message_data.spam_count, 
                        message_data.not_spam_count,
                        message_data.forwarded_message_id or 0,  # Include forwarded_message_id (use 0 if None)
                        message_data.forwarded_chat_id or 0,  # Include forwarded_chat_id (use 0 if None)
                        len(message_data.forwarded_message_content or '')  # Length of forwarded_message_content (use 0 if None)
                    ]
                ))

                features.append(feature_array)
                labels.append(message_data.is_spam)
                message_contents[message_data.id] = message_data.message_content

            logger.info("after messages_data loop")

            if not features:
                logger.info("No features to train on.")
                return None

            # Convert features and labels to NumPy arrays
            features = np.array(features)
            labels = np.array(labels)

            # Handle NaN values by imputing with the mean of each column
            imputer = SimpleImputer(strategy='mean')
            features = imputer.fit_transform(features)

            # Check the class distribution before splitting
            unique_classes, class_counts = np.unique(labels, return_counts=True)
            logger.info(f"Class distribution: {dict(zip(unique_classes, class_counts))}")

            # Split the data into training and testing sets using stratified splitting
            X_train, X_test, y_train, y_test, ids_train, ids_test = train_test_split(
                features, labels, list(message_contents.keys()), test_size=0.005, stratify=labels)

            # Check class distribution after splitting
            unique_train_classes, train_class_counts = np.unique(y_train, return_counts=True)
            unique_test_classes, test_class_counts = np.unique(y_test, return_counts=True)
            logger.info(f"Training class distribution: {dict(zip(unique_train_classes, train_class_counts))}")
            logger.info(f"Test class distribution: {dict(zip(unique_test_classes, test_class_counts))}")

            # Scale the features
            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train)
            X_test = scaler.transform(X_test)

            # Train the SVM model
            model = SVC(kernel='linear', probability=True)
            model.fit(X_train, y_train)

            # Evaluate the model
            accuracy = model.score(X_test, y_test)
            logger.info(f"🎉Model accuracy: {accuracy}")

            # Dump the trained model and scaler to file
            dump(model, 'ml_models/svm_spam_model.joblib')
            dump(scaler, 'ml_models/scaler.joblib')

            # Evaluate wrongly classified messages
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
