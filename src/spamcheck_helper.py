import numpy as np
import traceback
import os
from joblib import load
from datetime import datetime, timezone
from telegram.request import HTTPXRequest
from telegram import Bot
import re

# Import necessary helper modules
import src.db_helper as db_helper
import src.logging_helper as logging
import src.openai_helper as openai_helper
import src.rating_helper as rating_helper
import src.chat_helper as chat_helper
import src.user_helper as user_helper

logger = logging.get_logger()
bot = Bot(os.getenv('ENV_BOT_KEY'),
          request=HTTPXRequest(http_version="1.1"),
          get_updates_request=HTTPXRequest(http_version="1.1"))

current_path = os.getcwd()
print("Current Working Directory:", current_path)

model = load('ml_models/svm_spam_model.joblib')
scaler = load('ml_models/scaler.joblib')

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
            # Compute time difference in seconds
            time_difference = (message_date - joined_date).total_seconds()
            message_length = len(message_text) if message_text else 0
            # New feature: check if the message text contains a Telegram username (e.g., "@rvnikita")
            has_telegram_nick = 1.0 if re.search(r'@\w+', message_text) else 0.0

            is_forwarded = is_forwarded or 0
            reply_to_message_id = reply_to_message_id or 0

            # Construct the feature array in the same order as used during training:
            # Order: embedding, user_rating_value, time_difference, chat_id, user_id, message_length,
            # spam_count, not_spam_count, is_forwarded, reply_to_message_id, has_telegram_nick
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
                float(reply_to_message_id),
                has_telegram_nick
            ])
            return feature_array
    except Exception as e:
        logger.error(f"An error occurred during feature generation: {traceback.format_exc()}")
        return None

async def predict_spam(user_id, chat_id, message_content=None, embedding=None, is_forwarded=None, reply_to_message_id=None):
    try:
        feature_array = await generate_features(
            user_id, chat_id, message_content, embedding, is_forwarded, reply_to_message_id
        )
        if feature_array is None:
            logger.error("Feature array is None, skipping prediction.")
            return False
        if np.isnan(feature_array.astype(float)).any():
            logger.error(f"NaN values found in feature_array: {feature_array}")
            return False
        feature_array = scaler.transform([feature_array])
        return model.predict_proba(feature_array)[0][1]
    except Exception as e:
        logger.error(f"An error occurred during spam prediction: {traceback.format_exc()}")
        return False
