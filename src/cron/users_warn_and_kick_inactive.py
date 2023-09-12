import sys
sys.path.insert(0, '../')
from datetime import datetime, timedelta
from sqlalchemy import and_, text
import os
import telegram
from telegram.request import HTTPXRequest
import asyncio
import traceback

sys.path.append('../../../')

import src.config_helper as config_helper
import src.logging_helper as logging_helper
import src.db_helper as db_helper
import src.user_helper as user_helper

config = config_helper.get_config()
logger = logging_helper.get_logger()

logger.info(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = telegram.Bot(token=config['BOT']['KEY'],
                   request=HTTPXRequest(http_version="1.1"),
                   get_updates_request=HTTPXRequest(http_version="1.1"))


async def warn_inactive(chat_id, inactivity_period_in_days_to_warn):
    try:
        with db_helper.session_scope() as session:
            inactive_users = session.query(db_helper.User_Status).filter(
                and_(
                    db_helper.User_Status.last_message_datetime < datetime.now() - timedelta(days=inactivity_period_in_days_to_warn),
                    db_helper.User_Status.status == 'member',
                    db_helper.User_Status.chat_id == chat_id,
                    db_helper.User_Status.status != 'kicked'  # Exclude users with 'kicked' status
                )
            ).all()

            mentions = [user_helper.get_user_mention(user.user.id) for user in inactive_users]
            joined_mentions = ', '.join(mentions[:-1]) + f" and {mentions[-1]}" if mentions else ""
            warn_text = f"❗️ List of potential inactive candidates for deletion this month: {joined_mentions}. ..."
            await bot.send_message(chat_id=chat_id, text=warn_text)
    except Exception as e:
        logger.error(f"Error occurred during warn_inactive: {str(e)}\n{traceback.format_exc()}")

async def kick_inactive(chat_id, inactivity_period_in_days_to_kick):
    try:
        with db_helper.session_scope() as session:
            inactive_users = session.query(db_helper.User_Status).filter(
                and_(
                    db_helper.User_Status.last_message_datetime < datetime.now() - timedelta(days=inactivity_period_in_days_to_kick),
                    db_helper.User_Status.status == 'member',
                    db_helper.User_Status.chat_id == chat_id
                )
            ).all()

            for user_status in inactive_users:
                try:
                    user_mention = user_helper.get_user_mention(user_status.user.id)
                    await bot.ban_chat_member(chat_id, user_status.user_id)
                    await bot.send_message(chat_id,f"User {user_mention} was kicked for inactivity")
                    user_status.status = 'kicked' # Updating the user status after they're kicked
                    session.commit()  # Committing the changes to the database
                    logger.info(f"User {user_mention} was kicked for inactivity")
                except Exception as e:
                    logger.error(f"Error occurred while kicking out user {user_mention}: {str(e)}\n{traceback.format_exc()}")

    except Exception as e:
        logger.error(f"Error occurred during kick_inactive: {str(e)}\n{traceback.format_exc()}")

async def main() -> None:
    try:
        print("Starting users_warn_and_kick_inactive.py")

        with db_helper.session_scope() as session:
            kick_inactive_chats = session.query(db_helper.Chat).filter(
                text("(config->>'kick_inactive')::int > 0")).all()
            for chat in kick_inactive_chats:
                await kick_inactive(chat.id, chat.config["kick_inactive"])

            warn_inactive_chats = session.query(db_helper.Chat).filter(
                text("(config->>'warn_inactive')::int > 0")).all()
            for chat in warn_inactive_chats:
                await warn_inactive(chat.id, chat.config["warn_inactive"])

    except Exception as e:
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())
