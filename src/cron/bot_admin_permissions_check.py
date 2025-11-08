import sys
sys.path.insert(0, '../')  # add parent directory to the path

import asyncio
from datetime import datetime, timedelta, timezone
import telegram
from telegram.error import BadRequest, Forbidden
import traceback
import psycopg2
import psycopg2.extras
import os

import src.helpers.db_helper as db_helper
import src.helpers.chat_helper as chat_helper
import src.helpers.logging_helper as logging_helper

# Setup configuration and logger as before
logger = logging_helper.get_logger()
bot = telegram.Bot(token=os.getenv('ENV_BOT_KEY'))

async def admin_permissions_check():
    logger.info("Starting admin permissions check cron script")

    await bot.initialize()

    with db_helper.connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Retrieve chats that haven't been checked in the last day
            sql = """
            SELECT id, chat_name FROM tg_chat
            WHERE last_admin_permission_check IS NULL OR last_admin_permission_check < %s
            """
            one_day_ago = datetime.now(timezone.utc) - timedelta(hours=20)
            cur.execute(sql, (one_day_ago,))
            chat_rows = cur.fetchall()

            for chat_row in chat_rows:
                chat_id = chat_row['id']
                chat_name = chat_row['chat_name']

                # Skip invalid chat IDs (0 is not a valid Telegram chat ID)
                if chat_id == 0:
                    logger.warning(f"Skipping invalid chat ID 0 for chat '{chat_name}'. This record should be cleaned up.")
                    continue

                try:
                    logger.info(f"Checking admin permissions for {chat_name} ({chat_id})")

                    now = datetime.now(timezone.utc)
                    await chat_helper.set_last_admin_permissions_check(chat_id, now)

                    # Now only chats that were not checked in the last day are processed
                    chat_administrators = await chat_helper.get_chat_administrators(bot, chat_id)
                    bot_is_admin = any(admin["user_id"] == bot.id for admin in chat_administrators)

                    if not bot_is_admin:
                        message_text = "Bot is not an admin in this chat. Please make me an admin to operate fully."
                        await chat_helper.send_message(bot, chat_id, message_text)
                        logger.info(f"Notification sent to chat {chat_name} ({chat_id}): {message_text}")
                    else:
                        logger.info(f"Bot is an admin in chat {chat_name} ({chat_id})")
                except BadRequest as e:
                    if "Chat not found" in str(e):
                        logger.info(f"Chat not found for {chat_name} ({chat_id}).")
                    elif "Topic_closed" in str(e):
                        logger.info(f"Topic is closed in chat {chat_name} ({chat_id}). Skipping admin check for this chat.")
                    else:
                        logger.error(f"Error checking admin permissions for {chat_name} ({chat_id}): {e.message}")
                except Forbidden as e:
                    logger.info(f"Forbidden: Bot is not a member of the group chat {chat_name} ({chat_id}).")
                except Exception as e:
                    logger.error(f"Unexpected error for {chat_name} ({chat_id}): {traceback.format_exc()}")
            conn.commit()

async def main():
    try:
        await admin_permissions_check()
    except Exception as e:
        logger.error(f"Error during admin permissions check: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(main())