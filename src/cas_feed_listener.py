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
            logger.debug(f"CAS-banned user id: {user_id}")

            # 2) Gather chats where they’re known (status or past messages) in one query
            with db_helper.session_scope() as session:
                sub1 = session.query(db_helper.User_Status.chat_id).filter(db_helper.User_Status.user_id == user_id)
                sub2 = session.query(db_helper.Message_Log.chat_id).filter(db_helper.Message_Log.user_id == user_id)
                rows = sub1.union(sub2).distinct().all()
                chat_ids = [cid for (cid,) in rows]

                if not chat_ids:
                    logger.info(f"CAS-banned user id: {user_id} - no record found, skipping")
                    continue
                else:
                    logger.info(f"CAS-banned user id: {user_id} - found in chats: {chat_ids}")

                # 1) Add to global-ban table only if we've seen this user
                ban = session.query(db_helper.User_Global_Ban).filter_by(user_id=user_id).one_or_none()
                if not ban:
                    session.add(db_helper.User_Global_Ban(user_id=user_id, reason="cas"))
                    logger.info(f"📌 Added user {user_id} to User_Global_Ban (reason=cas)")

                # 4) Mark all their past messages as spam in one query
                count = session.query(db_helper.Message_Log)\
                    .filter(db_helper.Message_Log.user_id == user_id)\
                    .update({
                        db_helper.Message_Log.is_spam: True,
                        db_helper.Message_Log.manually_verified: True,
                        db_helper.Message_Log.reason_for_action: "cas"
                    }, synchronize_session=False)
                if count:
                    logger.info(f"Marked {count} messages as spam for user {user_id}")

            # 3) Global mute
            try:
                await chat_helper.mute_user(bot, 0, user_id, global_mute=True)
                logger.info(f"🚨 CAS-banned user id: {user_id} globally muted")
            except Exception as e:
                logger.error(f"Failed to global-mute user {user_id}: {e}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
