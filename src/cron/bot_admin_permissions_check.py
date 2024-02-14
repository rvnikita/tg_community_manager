import sys
sys.path.insert(0, '../')  # add parent directory to the path

import asyncio
from datetime import datetime, timedelta
import src.db_helper as db_helper
import src.chat_helper as chat_helper
import src.config_helper as config_helper
import src.logging_helper as logging_helper
import telegram
from telegram.error import BadRequest  # Corrected import
import traceback
import psycopg2
import psycopg2.extras

# Setup configuration and logger as before
config = config_helper.get_config()
logger = logging_helper.get_logger()
bot = telegram.Bot(token=config['BOT']['KEY'])

async def initialize_bot():
    """Initialize the bot before use."""
    await bot.initialize()


async def admin_permissions_check():
    logger.info("Starting admin permissions check cron script")

    # Initialize the bot before starting the checks
    await initialize_bot()

    with db_helper.connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Retrieve all chats from your database
            sql = "SELECT id, chat_name FROM tg_chat"
            cur.execute(sql)
            chat_rows = cur.fetchall()

            for chat_row in chat_rows:
                chat_id = chat_row['id']
                chat_name = chat_row['chat_name']
                try:
                    logger.info(f"Checking admin permissions for {chat_name} ({chat_id})")
                    # Perform the admin permissions check as before
                    last_notified = await chat_helper.get_last_admin_permissions_check(chat_id)
                    now = datetime.now()

                    if last_notified is None or (now - last_notified) >= timedelta(days=1):
                        chat_administrators = await bot.get_chat_administrators(chat_id)
                        bot_is_admin = any(admin.user.id == bot.id for admin in chat_administrators)

                        if not bot_is_admin:
                            message_text = "Bot is not an admin in this chat. Please make me an admin to operate fully."
                            await chat_helper.send_message(bot, chat_id, message_text)
                            logger.info(f"Notification sent to chat ID: {chat_id}, Message: {message_text}")
                            await chat_helper.set_last_admin_permissions_check(chat_id, now)
                except BadRequest as e:
                    if "Chat not found" in str(e):
                        # Log as info if the chat is not found
                        logger.info(f"Chat not found for {chat_name} ({chat_id}).")
                    else:
                        # Otherwise, log as error
                        logger.error(f"Error checking admin permissions for {chat_name} ({chat_id}): {e.message}")
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