import numpy as np
import traceback
from joblib import load
from datetime import datetime, timezone
from telegram.request import HTTPXRequest
from telegram import Bot

# Import necessary helper modules
import src.db_helper as db_helper
import src.logging_helper as logging
import src.openai_helper as openai_helper
import src.rating_helper as rating_helper
import src.config_helper as config_helper
import src.chat_helper as chat_helper
import src.user_helper as user_helper

# Configure logger
logger = logging.get_logger()
config = config_helper.get_config()
bot = Bot(config['BOT']['KEY'],
          request=HTTPXRequest(http_version="1.1"),
          get_updates_request=HTTPXRequest(http_version="1.1"))

# Load the pre-trained SVM model
import os

current_path = os.getcwd()
print("Current Working Directory:", current_path)

model = load('ml_models/svm_spam_model.joblib')
scaler = load('ml_models/scaler.joblib')

import numpy as np
import traceback
from datetime import datetime, timezone

async def generate_features(user_id, chat_id, message_text=None, embedding=None, is_forwarded=None, reply_to_message_id=None):
    try:
        if embedding is None and message_text is not None:
            embedding = openai_helper.generate_embedding(message_text)

        if embedding is None:
            logger.error(f"Failed to generate embedding for spam prediction. Message text: {message_text}")
            return None

        with db_helper.session_scope() as session:
            user = session.query(db_helper.User).filter(db_helper.User.id == user_id).one_or_none()
            if not user:
                logger.error(f"User with ID {user_id} not found.")
                return None

            user_status = session.query(db_helper.User_Status).filter(
                db_helper.User_Status.user_id == user_id,
                db_helper.User_Status.chat_id == chat_id
            ).one_or_none()

            spam_count = session.query(db_helper.Message_Log).filter(
                db_helper.Message_Log.user_id == user_id,
                db_helper.Message_Log.is_spam == True
            ).count()

            not_spam_count = session.query(db_helper.Message_Log).filter(
                db_helper.Message_Log.user_id == user_id,
                db_helper.Message_Log.is_spam == False
            ).count()

            user_rating_value = rating_helper.get_rating(user_id, chat_id)
            joined_date = user_status.created_at if user_status else user.created_at
            message_date = datetime.now(timezone.utc)
            time_difference = (message_date - joined_date).days
            message_length = len(message_text) if message_text else 0

            # Default values for the new columns if they are None
            is_forwarded = is_forwarded or 0
            reply_to_message_id = reply_to_message_id or 0

            # Construct feature array
            feature_array = np.array([
                *embedding, 
                float(user_rating_value), 
                float(time_difference), 
                float(chat_id), 
                float(user_id), 
                float(message_length), 
                float(spam_count), 
                float(not_spam_count), 
                float(is_forwarded), 
                float(reply_to_message_id)
            ])

            # Log the shape of the feature array
            logger.info(f"Generated feature array with shape: {feature_array.shape}")

            return feature_array
    except Exception as e:
        logger.error(f"An error occurred during feature generation: {traceback.format_exc()}")
        return None



async def predict_spam(user_id, chat_id, message_content=None, embedding=None, is_forwarded=None, reply_to_message_id=None):
    try:
        feature_array = await generate_features(
            user_id, chat_id, message_content, embedding, 
            is_forwarded, reply_to_message_id
        )
        if feature_array is None:
            logger.error("Feature array is None, skipping prediction.")
            return False

        if np.isnan(feature_array.astype(float)).any():  # Ensure feature_array is float type
            logger.error(f"NaN values found in feature_array: {feature_array}")
            return False

        feature_array = scaler.transform([feature_array])  # Reshape for scaler
        return model.predict_proba(feature_array)[0][1]

    except Exception as e:
        logger.error(f"An error occurred during spam prediction: {traceback.format_exc()}")
        logger.error(f"Feature array at time of error: {feature_array}")
        return False
