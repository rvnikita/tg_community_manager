import sys
sys.path.insert(0, '../') # add parent directory to the path
from datetime import datetime, timedelta
from sqlalchemy import and_, Integer, cast, text
import os
import telegram
from telegram.request import HTTPXRequest
import asyncio
import traceback

import src.config_helper as config_helper
import src.logging_helper as logging_helper
import src.db_helper as db_helper
import src.user_helper as user_helper

config = config_helper.get_config()
logger = logging_helper.get_logger()

logger.info(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = telegram.Bot(token=config['BOT']['KEY'],
                   request=HTTPXRequest(http_version="1.1"),  #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
                   get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556

async def warn_inactive(chat_id, inactivity_period_in_days_to_warn):
    try:
        with db_helper.session_scope() as session:
            # Your query goes here
            inactive_users = session.query(db_helper.User_Status).filter(
                and_(
                    db_helper.User_Status.last_message_datetime < datetime.now() - timedelta(days=inactivity_period_in_days_to_warn),
                    db_helper.User_Status.status == 'member',
                    db_helper.User_Status.chat_id == chat_id
                )
            ).all()

            # Extract mentions from the inactive users using get_user_mention
            mentions = [user_helper.get_user_mention(user.user.id) for user in inactive_users]

            # Join all mentions with comma and last with "and "
            joined_mentions = ', '.join(mentions[:-1]) + f" and {mentions[-1]}" if mentions else ""

            # Prepare the warning text
            warn_text = f"❗️ List of potential inactive candidates for deletion this month: {joined_mentions}. We have not heard anything from them for at least {inactivity_period_in_days_to_warn} days :( We value your presence! Sharing something useful, fun or insightful keeps our chat vibrant. Plus, it ensures your spot here - just post at least once every {inactivity_period_in_days_to_warn} days. Looking forward to your contributions! 😊"

            # Send the warning message
            await bot.send_message(chat_id=chat_id, text=warn_text)
    except Exception as e:
        logger.error(f"Error occurred during warn_inactive: {str(e)}\n{traceback.format_exc()}")


async def kick_inactive(chat_id, inactivity_period_in_days_to_kick):
    try:
        with db_helper.session_scope() as session:
            # Query for the inactive users to be deleted
            inactive_users = session.query(db_helper.User_Status).filter(
                and_(
                    db_helper.User_Status.last_message_datetime < datetime.now() - timedelta(days=inactivity_period_in_days_to_kick),
                    db_helper.User_Status.status == 'member',
                    db_helper.User_Status.chat_id == chat_id
                )
            ).all()

            # Iterate over inactive users and kick them out of the chat
            for user_status in inactive_users:
                try:
                    user_mention = user_helper.get_user_mention(user_status.user.id)
                    # await bot.kick_chat_member(chat_id, user_status.user_id)
                    #write to chat that we kicked inactive user
                    await bot.send_message(chat_id,f"User {user_mention} was kicked for inactivity")

                    logger.info(f"User {user_mention} was kicked for inactivity")
                except Exception as e:
                    logger.error(f"Error occurred while kicking out user {user_mention}: {str(e)}\n{traceback.format_exc()}")

    except Exception as e:
        logger.error(f"Error occurred during kick_inactive: {str(e)}\n{traceback.format_exc()}")

async def main() -> None:
    try:
        with db_helper.session_scope() as session:

            # Get chat configs where "kick_inactive" > 0
            # We kick first to make sure we don't Warn someone who we will kick at the same time
            kick_inactive_chats = session.query(db_helper.Chat).filter(
                text("(config->>'kick_inactive')::int > 0")).all()
            for chat in kick_inactive_chats:
                await kick_inactive(chat.id, chat.config["kick_inactive"])

            # Get chat configs where "warn_inactive" > 0
            warn_inactive_chats = session.query(db_helper.Chat).filter(
                text("(config->>'warn_inactive')::int > 0")).all()
            for chat in warn_inactive_chats:
                await warn_inactive(chat.id, chat.config["warn_inactive"])

    except Exception as e:
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())
