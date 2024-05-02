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
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)


# Load the pre-trained SVM model
model = load('../../ml_models/svm_spam_model.joblib')
scaler = load('../../ml_models/scaler.joblib')

async def generate_features(message_text, user_id, chat_id):
    embedding = openai_helper.generate_embedding(message_text)
    if embedding is None:
        logger.error("Failed to generate embedding for spam prediction.")
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

        user_rating_value = rating_helper.get_rating(user_id, chat_id)
        joined_date = user_status.created_at if user_status else user.created_at
        message_date = datetime.now(timezone.utc)
        time_difference = (message_date - joined_date).days

        feature_array = np.concatenate((embedding, [user_rating_value, time_difference]))
        return feature_array

async def predict_spam(message_text, user_id, chat_id):
    try:
        feature_array = await generate_features(message_text, user_id, chat_id)
        if feature_array is None:
            return False

        feature_array = scaler.transform([feature_array])  # Reshape for scaler
        prediction_proba = model.predict_proba(feature_array)
        threshold = config['ANTISPAM']['THRESHOLD']

        if prediction_proba[0][1] >= float(threshold):
            spam_detected = True
            logger.info(f"‼️Spam ‼️ Probability: {prediction_proba[0][1]:.5f}. Threshold: {threshold}. Message: {message_text}. Chat:  {await chat_helper.get_chat_mention(bot, chat_id)}. User: {await user_helper.get_user_mention(bot, user_id)}")
        else:
            spam_detected = False
            logger.info(f"Not Spam. Probability: {prediction_proba[0][1]:.5f}. Threshold: {threshold}. Message: {message_text}. Chat:  {await chat_helper.get_chat_mention(bot, chat_id)}. User: {await user_helper.get_user_mention(bot, user_id)}")

        return spam_detected

    except Exception as e:
        logger.error(f"An error occurred during spam prediction: {traceback.format_exc()}")
        return False