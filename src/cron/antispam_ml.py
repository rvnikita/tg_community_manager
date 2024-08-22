import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
import traceback
from joblib import dump
import asyncio

import sys
import os
sys.path.append(os.getcwd())

# Import necessary helper modules
import src.spamcheck_helper as spamcheck_helper
import src.db_helper as db_helper
import src.logging_helper as logging

# Configure logger
logger = logging.get_logger()

async def train_spam_classifier():
    """Train a simple SVM model for spam detection using message embeddings, content, user ratings, and time difference."""
    try:
        with db_helper.session_scope() as session:
            # Fetch the first 500 messages ordered by ID in descending order
            messages = session.query(db_helper.Message_Log) \
                              .filter(db_helper.Message_Log.embedding != None,
                                      db_helper.Message_Log.message_content != None) \
                              .order_by(db_helper.Message_Log.id.desc()) \
                              .limit(500)  # Limit to 500 messages

            features = []
            labels = []
            message_contents = {}  # Dictionary to store message contents for reference

            for message in messages:
                feature_array = await spamcheck_helper.generate_features(
                    message.user_id, message.chat_id, message.message_content, message.embedding
                )
                if feature_array is not None:
                    features.append(feature_array)
                    labels.append(message.is_spam)
                    message_contents[message.id] = message.message_content  # Store content for logging purposes

            if not features:
                logger.info("No features to train on.")
                return None

            features = np.array(features)
            labels = np.array(labels)

            X_train, X_test, y_train, y_test, ids_train, ids_test = train_test_split(
                features, labels, list(message_contents.keys()), test_size=0.2, random_state=42)

            scaler = StandardScaler().fit(X_train)
            X_train = scaler.transform(X_train)
            X_test = scaler.transform(X_test)

            model = SVC(kernel='linear', probability=True)
            model.fit(X_train, y_train)
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
