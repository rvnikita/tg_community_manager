from telegram import Bot
from telegram.request import HTTPXRequest
from sqlalchemy import func
import asyncio

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

async def change_rating(user_id_or_ids, judge_id, chat_id, change_value, message_id=None, announce=True):
    # If we receive a single user_id, convert it to a list
    user_ids = user_id_or_ids if isinstance(user_id_or_ids, list) else [user_id_or_ids]

    with db_helper.session_scope() as db_session:
        chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat_id).first()
        if chat is None:
            return  # Handle error: chat not found

        group_id = chat.group_id
        messages = []

        for user_id in user_ids:
            if group_id is None:
                # If group_id is null, get ratings only for this specific chat
                user_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
                    db_helper.User_Rating.user_id == user_id,
                    db_helper.User_Rating.chat_id == chat_id)
            else:
                # If group_id is not null, get ratings for all chats in the group
                user_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
                    db_helper.User_Rating.user_id == user_id,
                    db_helper.Chat.group_id == group_id,
                    db_helper.Chat.id == db_helper.User_Rating.chat_id)

            user_total_rating = user_total_rating_query.scalar() or 0

            # Determine the rating action
            if change_value >= 1:
                rating_action = "increased"
            elif change_value <= -1:
                rating_action = "decreased"
            else:
                rating_action = "not changed"

            user_mention = user_helper.get_user_mention(user_id)
            messages.append(f"{rating_action} reputation of {user_mention} ({user_total_rating + change_value})")

            user_rating = db_helper.User_Rating(user_id=user_id, chat_id=chat_id, judge_id=judge_id, change_value=change_value)
            db_session.add(user_rating)

        db_session.commit()

        judge_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
            db_helper.User_Rating.user_id == judge_id,
            db_helper.User_Rating.chat_id == chat_id)
        judge_total_rating = judge_total_rating_query.scalar() or 0

        judge_mention = user_helper.get_user_mention(judge_id)

        # Decide the message format based on the number of user_ids
        if len(user_ids) == 1:
            text_to_send = f"{judge_mention} ({judge_total_rating}) {messages[0]}"
        else:
            text_to_send = f"{judge_mention} ({judge_total_rating}) has:\n" + '\n'.join(messages)

        if announce:
            if message_id is None:
                await chat_helper.send_message(bot, chat_id, text_to_send, delete_after = 120)
            else:
                #TODO:MED: Maybe we need to wrap bot.send_message to add delete_delay parameter and not copy the same code again and again
                await chat_helper.send_message(bot, chat_id, text_to_send, reply_to_message_id=message_id, delete_after=120)

        logger.info(text_to_send + f" in chat {await chat_helper.get_chat_mention(bot, chat_id)}")




