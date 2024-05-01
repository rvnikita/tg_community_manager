import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
import traceback
from joblib import dump

# Import necessary helper modules
import src.db_helper as db_helper
import src.logging_helper as logging
import src.rating_helper as rating_helper

# Configure logger
logger = logging.get_logger()

def train_spam_classifier():
    """Train a simple SVM model for spam detection using message embeddings, content, user ratings, and time difference."""
    try:
        with db_helper.session_scope() as session:
            # Fetch messages and statuses from database
            messages_with_content_embeddings = session.query(db_helper.Message_Log, db_helper.User_Status) \
                .join(db_helper.User, db_helper.Message_Log.user_id == db_helper.User.id) \
                .outerjoin(db_helper.User_Status, (db_helper.Message_Log.user_id == db_helper.User_Status.user_id) & \
                           (db_helper.Message_Log.chat_id == db_helper.User_Status.chat_id)) \
                .filter(db_helper.Message_Log.embedding != None) \
                .filter(db_helper.Message_Log.message_content != None) \
                .all()

            features = []
            labels = []
            message_contents = {}
            message_ids = []

            for message, user_status in messages_with_content_embeddings:
                user_rating_value = rating_helper.get_rating(message.user_id, message.chat_id)
                if user_status:
                    joined_date = user_status.created_at
                else:
                    joined_date = message.user.created_at
                message_date = message.message_timestamp
                time_difference = (message_date - joined_date).days

                feature_array = np.concatenate((message.embedding, [user_rating_value, time_difference]))
                features.append(feature_array)
                labels.append(message.is_spam)
                message_contents[message.id] = message.message_content
                message_ids.append(message.id)

            features = np.array(features)
            labels = np.array(labels)

            X_train, X_test, y_train, y_test, ids_train, ids_test = train_test_split(
                features, labels, message_ids, test_size=0.2, random_state=42
            )

            scaler = StandardScaler()
            X_train = scaler.fit_transform(X_train)
            X_test = scaler.transform(X_test)

            model = SVC(kernel='linear')
            model.fit(X_train, y_train)
            accuracy = model.score(X_test, y_test)
            logger.info(f"Model accuracy: {accuracy}")

            # Dump the trained model and scaler to file
            dump(model, '../../ml_models/svm_spam_model.joblib')
            dump(scaler, '../../ml_models/scaler.joblib')

            logger.info("Model and scaler have been saved successfully.")

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
    train_spam_classifier()
