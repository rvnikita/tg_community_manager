import numpy as np
import traceback
from joblib import load
from datetime import datetime, timezone

# Import necessary helper modules
import src.db_helper as db_helper
import src.logging_helper as logging
import src.openai_helper as openai_helper

# Configure logger
logger = logging.get_logger()

# Load the pre-trained SVM model
model = load('ml_models/svm_spam_model.joblib')
scaler = load('ml_models/scaler.joblib')

def predict_spam(message_text, user_id, chat_id):
    try:
        # Calculate embedding for the message
        embedding = openai_helper.generate_embedding(message_text)
        if embedding is None:
            logger.error("Failed to generate embedding for spam prediction.")
            return False

        # Fetch additional features from the database
        with db_helper.session_scope() as session:
            user = session.query(db_helper.User).filter(db_helper.User.id == user_id).one_or_none()
            if not user:
                logger.error(f"User with ID {user_id} not found.")
                return False

            user_status = session.query(db_helper.User_Status).filter(
                db_helper.User_Status.user_id == user_id,
                db_helper.User_Status.chat_id == chat_id
            ).one_or_none()

            # Calculate user rating value
            user_rating_value = sum(r.change_value for r in user.user_ratings) if hasattr(user, 'user_ratings') else 0

            # Calculate the time difference using current time from datetime module
            if user_status:
                joined_date = user_status.created_at
            else:
                joined_date = user.created_at

            message_date = datetime.now(timezone.utc)  # Using current UTC time, now timezone-aware
            time_difference = (message_date - joined_date).days

            # Prepare the feature vector
            feature_array = np.array([*embedding, user_rating_value, time_difference])
            feature_array = scaler.transform([feature_array])  # Scale features using the loaded scaler

            # Predict using the SVM model
            prediction = model.predict(feature_array)
            return prediction[0] == 1  # Return True if model predicts '1' for spam

    except Exception as e:
        logger.error(f"An error occurred during spam prediction: {traceback.format_exc()}")
        return False