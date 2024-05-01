import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC
import traceback

from src.config_helper import get_config
from src.db_helper import session_scope, Message_Log
from src.logging_helper import get_logger

# Configure logger
logger = get_logger()

# Load configuration
config = get_config()

def train_spam_classifier():
    """Train a simple SVM model for spam detection using message embeddings."""
    try:
        # Retrieve messages with embeddings and labels
        with session_scope() as session:
            messages_with_embeddings = session.query(Message_Log).filter(Message_Log.embedding != None).all()
            embeddings = [message.embedding for message in messages_with_embeddings]
            labels = [message.is_spam for message in messages_with_embeddings]

        # Split data into train and test sets
        X_train, X_test, y_train, y_test = train_test_split(np.array(embeddings), labels, test_size=0.2, random_state=42)

        # Train SVM model
        model = SVC(kernel='linear')
        model.fit(X_train, y_train)

        # Evaluate model
        accuracy = model.score(X_test, y_test)
        logger.info(f"Model accuracy: {accuracy}")

        return model
    except Exception as e:
        logger.error(f"An error occurred while training the spam classifier: {e}. Traceback: {traceback.format_exc()}")
        return None

if __name__ == '__main__':
    try:
        trained_model = train_spam_classifier()
        if trained_model:
            logger.info("Spam classifier trained successfully.")
        else:
            logger.error("Failed to train spam classifier.")
    except Exception as e:
        logger.error(f"An error occurred in the main block: {e}. Traceback: {traceback.format_exc()}")
