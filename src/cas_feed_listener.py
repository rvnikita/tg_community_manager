import os
import re
import asyncio

import dotenv
from telethon import TelegramClient, events
import telegram
import telegram.request

import logging_helper
import src.db_helper as db_helper
import src.chat_helper as chat_helper
import src.message_helper as message_helper

dotenv.load_dotenv("config/.env")
logger = logging_helper.get_logger()

client = TelegramClient(
    os.getenv("CAS_TELETHON_SESSION_NAME", "cas_telethon"),
    int(os.getenv("CAS_TELETHON_API_ID")),
    os.getenv("CAS_TELETHON_API_HASH"),
)

bot = telegram.Bot(
    os.getenv("ENV_BOT_KEY"),
    request=telegram.request.HTTPXRequest(http_version="1.1"),
)

CAS_PATTERN = re.compile(r"User\s+#(\d+)\s+has been CAS banned\b", re.IGNORECASE)

async def main():
    await client.start(os.getenv("CAS_TELETHON_PHONE_NUMBER"))
    me = await client.get_me()
    logger.info(f"CAS listener logged in as {me.username} (id={me.id})")

    @client.on(events.NewMessage(chats=os.getenv("CAS_FEED_CHANNEL", "cas_feed")))
    async def cas_handler(event):
        text = event.message.message or ""
        for match in CAS_PATTERN.finditer(text):
            user_id = int(match.group(1))

            # collect chats where user has a status
            with db_helper.session_scope() as session:
                rows = session.query(db_helper.User_Status.chat_id)\
                              .filter_by(user_id=user_id)\
                              .all()
            chat_ids = [cid for (cid,) in rows]

            # fallback: chats where user sent messages
            if not chat_ids:
                with db_helper.session_scope() as session:
                    rows = session.query(db_helper.Message_Log.chat_id)\
                                  .filter(db_helper.Message_Log.user_id == user_id)\
                                  .distinct()\
                                  .all()
                chat_ids = [cid for (cid,) in rows]

            if not chat_ids:
                logger.info(f"Extracted CAS-banned user id: {user_id} - no chats found, skipping")
                continue

            logger.info(f"Extracted CAS-banned user id: {user_id} - muting in {len(chat_ids)} chats")
            for chat_id in chat_ids:
                try:
                    await chat_helper.mute_user(bot, chat_id, user_id)
                except Exception as e:
                    logger.error(f"Failed to mute user {user_id} in chat {chat_id}: {e}")

            # mark all their messages as spam
            with db_helper.session_scope() as session:
                logs = session.query(db_helper.Message_Log)\
                              .filter(db_helper.Message_Log.user_id == user_id)\
                              .all()

            if logs:
                for log in logs:
                    message_helper.insert_or_update_message_log(
                        chat_id=log.chat_id,
                        message_id=log.message_id,
                        is_spam=True,
                        manually_verified=True
                    )
                logger.info(f"Marked {len(logs)} messages as spam for user {user_id}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
