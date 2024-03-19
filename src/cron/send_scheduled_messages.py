import sys
import os
import traceback

sys.path.insert(0, '../')  # Add the parent directory to the path for module importing
import asyncio
import src.db_helper as db_helper
import src.chat_helper as chat_helper
import src.config_helper as config_helper
import src.logging_helper as logging_helper
import telegram
from telegram.request import HTTPXRequest

# Configuration and logging setup
config = config_helper.get_config()
logger = logging_helper.get_logger()
logger.info(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

# Initialize Telegram Bot
bot = telegram.Bot(token=config['BOT']['KEY'],
                   request=HTTPXRequest(http_version="1.1"))  # Fix for known bug

async def send_scheduled_messages():
    try:
        # The function from chat_helper that sends scheduled messages
        await chat_helper.send_scheduled_messages(bot)
    except Exception as e:
        logger.error(f"Error while sending scheduled messages: {traceback.format_exc()}")

async def main():
    try:
        await send_scheduled_messages()  # Call the function to send scheduled messages
    except Exception as e:
        logger.error(f"Unhandled error in main coroutine: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(main())
