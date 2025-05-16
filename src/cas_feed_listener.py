import os
import re
import asyncio

import dotenv
import telethon
import telegram
import telegram.request

import logging_helper
import src.db_helper as db_helper
import src.chat_helper as chat_helper

dotenv.load_dotenv("config/.env")
logger = logging_helper.get_logger()

client = telethon.TelegramClient(
    os.getenv("CAS_TELETHON_SESSION_NAME", "cas_telethon"),
    int(os.getenv("CAS_TELETHON_API_ID")),
    os.getenv("CAS_TELETHON_API_HASH"),
)

bot = telegram.Bot(
    os.getenv("ENV_BOT_KEY"),
    request=telegram.request.HTTPXRequest(http_version="1.1"),
)

async def main():
    await client.start(os.getenv("CAS_TELETHON_PHONE_NUMBER"))
    me = await client.get_me()
    logger.info(f"CAS listener logged in as {me.username} (id={me.id})")

    @client.on(telethon.events.NewMessage(chats=os.getenv("CAS_FEED_CHANNEL", "cas_feed")))
    async def cas_handler(event):
        text = event.message.message or ""
        for uid in re.findall(r"#(\d+)", text):
            user_id = int(uid)
            with db_helper.session_scope() as session:
                user = session.query(db_helper.User).filter_by(id=user_id).first()
            if user:
                await chat_helper.mute_user(bot, user.chat_id, user_id)
                logger.info(f"Muted user {user_id} in chat {user.chat_id} due to CAS ban")
            else:
                logger.info(f"CAS ban for unknown user {user_id}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
