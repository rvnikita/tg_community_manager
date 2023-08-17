from telegram import Bot
from telegram.request import HTTPXRequest
from sqlalchemy import func

import src.db_helper as db_helper
import src.user_helper as user_helper
import src.logging_helper as logging
import src.config_helper as config_helper
import src.chat_helper as chat_helper

logger = logging.get_logger()

config = config_helper.get_config()

bot = Bot(config['BOT']['KEY'],
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

async def change_rating(user_id, judge_id, chat_id, change_value, message_id=None, announce=True):
    with db_helper.session_scope() as db_session:
        chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat_id).first()
        if chat is None:
            return  # Handle error: chat not found

        group_id = chat.group_id

        if group_id is None:
            # If group_id is null, get ratings only for this specific chat
            user_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
                db_helper.User_Rating.user_id == user_id,
                db_helper.User_Rating.chat_id == chat_id)
            judge_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
                db_helper.User_Rating.user_id == judge_id,
                db_helper.User_Rating.chat_id == chat_id)
        else:
            # If group_id is not null, get ratings for all chats in the group
            user_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
                db_helper.User_Rating.user_id == user_id,
                db_helper.Chat.group_id == group_id,
                db_helper.Chat.id == db_helper.User_Rating.chat_id)
            judge_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
                db_helper.User_Rating.user_id == judge_id,
                db_helper.Chat.group_id == group_id,
                db_helper.Chat.id == db_helper.User_Rating.chat_id)

        user_total_rating = user_total_rating_query.scalar() or 0
        judge_total_rating = judge_total_rating_query.scalar() or 0

        # Add a new User_Rating record for each rating change
        user_rating = db_helper.User_Rating(user_id=user_id, chat_id=chat_id, judge_id=judge_id, change_value=change_value)
        db_session.add(user_rating)
        db_session.commit()

        # Determine the rating action
        if change_value >= 1:
            rating_action = "increased"
        elif change_value <= -1:
            rating_action = "decreased"
        else:
            rating_action = "not changed"
            pass

        user_mention = user_helper.get_user_mention(user_id)
        judge_mention = user_helper.get_user_mention(judge_id)

        text_to_send = f"{judge_mention} ({judge_total_rating}) {rating_action} reputation of {user_mention} ({user_total_rating})"

        if announce == True:
            if message_id is None:
                await bot.send_message(chat_id=chat_id, text=text_to_send)
            else:
                await bot.send_message(chat_id=chat_id, text=text_to_send, reply_to_message_id=message_id)

        logger.info(text_to_send + f" in chat {await chat_helper.get_chat_mention(bot, chat_id)} ")


