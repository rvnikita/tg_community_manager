from telegram import Bot
from telegram.request import HTTPXRequest
from sqlalchemy import func
import asyncio
import traceback
import os

import src.helpers.db_helper as db_helper
import src.helpers.user_helper as user_helper
import src.helpers.logging_helper as logging_helper
import src.helpers.chat_helper as chat_helper

logger = logging_helper.get_logger()

bot = Bot(token=os.getenv('ENV_BOT_KEY'),
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

async def change_rating(user_id_or_ids, judge_id, chat_id, change_value, message_id=None, announce=True, delete_message_delay=0):
    try:
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

                user_mention = user_helper.get_user_mention(user_id, chat_id)
                messages.append(f"{rating_action} reputation of {user_mention}. New value is ({user_total_rating + change_value})")

                user_rating = db_helper.User_Rating(user_id=user_id, chat_id=chat_id, judge_id=judge_id, change_value=change_value)
                db_session.add(user_rating)

            db_session.commit()

            judge_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(
                db_helper.User_Rating.user_id == judge_id,
                db_helper.User_Rating.chat_id == chat_id)
            judge_total_rating = judge_total_rating_query.scalar() or 0

            judge_mention = user_helper.get_user_mention(judge_id, chat_id)

            # Decide the message format based on the number of user_ids
            if len(user_ids) == 1:
                text_to_send = f"{judge_mention} {messages[0]}"
            else:
                text_to_send = f"{judge_mention} has:\n" + '\n'.join(messages)

            if announce:
                if message_id is None:
                    await chat_helper.send_message(bot, chat_id, text_to_send, delete_after = delete_message_delay)
                else:
                    #TODO:MED: Maybe we need to wrap bot.send_message to add delete_delay parameter and not copy the same code again and again
                    await chat_helper.send_message(bot, chat_id, text_to_send, reply_to_message_id=message_id, delete_after = delete_message_delay)

            logger.info(text_to_send + f" in chat {await chat_helper.get_chat_mention(bot, chat_id)}")
    except Exception as e:
        logger.error(f"Error changing rating: {traceback.format_exc()}")


def get_rating(user_id, chat_id):
    try:
        with db_helper.session_scope() as db_session:
            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat_id).first()
            if chat is None:
                logger.error(f"Chat {chat_id} not found.")
                return None  # Handle error: chat not found

            # Check if there is a group_id associated with the chat
            if chat.group_id is not None:
                # Get ratings for all chats in the group
                user_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).join(db_helper.Chat, db_helper.User_Rating.chat_id == db_helper.Chat.id).filter(db_helper.User_Rating.user_id == user_id, db_helper.Chat.group_id == chat.group_id)
            else:
                # Get the total rating for the user in the specified chat
                user_total_rating_query = db_session.query(func.sum(db_helper.User_Rating.change_value)).filter(db_helper.User_Rating.user_id == user_id, db_helper.User_Rating.chat_id == chat_id)

            user_total_rating = user_total_rating_query.scalar() or 0
            return user_total_rating

    except Exception as e:
        logger.error(f"Error fetching rating for user_id {user_id}: {traceback.format_exc()}")
        return None  # Return None if there is an error


def get_total_rating(user_id):
    """Get total rating for a user across ALL chats."""
    try:
        with db_helper.session_scope() as db_session:
            user_total_rating = db_session.query(
                func.sum(db_helper.User_Rating.change_value)
            ).filter(
                db_helper.User_Rating.user_id == user_id
            ).scalar() or 0
            return user_total_rating
    except Exception as e:
        logger.error(f"Error fetching total rating for user_id {user_id}: {traceback.format_exc()}")
        return None