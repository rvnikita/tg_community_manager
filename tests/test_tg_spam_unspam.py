import os
import uuid
import pytest
import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telegram.ext import Application
from src.dispatcher import create_application  # returns a PTB Application
from src.helpers.db_helper import session_scope, Message_Log
import src.helpers.message_helper as message_helper
import src.helpers.chat_helper as chat_helper
import src.helpers.user_helper as user_helper

@pytest.mark.asyncio
async def test_tg_spam_unspam_flow():
    """
    Combined test for the /spam and /unspam commands:
      1. Ensure the target user is unbanned (using our helper) so he can join.
      2. The target user joins the chat and sends a spam message with a unique hash.
      3. A global admin sends the /spam command (as a reply) to mark the user’s messages as spam,
         delete recent messages (less than 24 hours old), etc.
      4. The test verifies in the database that all logs for the unique message are updated
         (is_spam=True, manually_verified=True) and that the spam message is deleted.
      5. Then, the global admin sends the /unspam command (as a reply).
      6. The test verifies that the logs are updated (is_spam=False, manually_verified=True)
         and that the target user can rejoin the chat and send a new message.
    """
    telethon_api_id = int(os.getenv("TELETHON1_API_ID", "0"))
    telethon_api_hash = os.getenv("TELETHON1_API_HASH", "")
    debug_chat_id = int(os.getenv("ENV_INFO_CHAT_ID", "0"))
    admin_session = os.getenv("TELETHON1_SESSION", "TELETHON1")
    target_session = os.getenv("TELETHON2_SESSION", "TELETHON2")

    # 1. Start the bot application.
    app: Application = create_application()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    # Get the PTB Bot instance from the application.
    ptb_bot = app.bot

    # 2. Ensure the target user is unbanned (if left banned from a previous run).
    async with TelegramClient(admin_session, telethon_api_id, telethon_api_hash) as admin_client:
        # Retrieve target user's ID using a Telethon client.
        async with TelegramClient(target_session, telethon_api_id, telethon_api_hash) as target_client:
            target_user = await target_client.get_me()
            target_user_id = target_user.id
        await chat_helper.unban_user(ptb_bot, debug_chat_id, target_user_id, global_unban=True)
        # Wait a short time for the unban to propagate.
        await asyncio.sleep(5)

    # 3. Target user joins the chat.
    async with TelegramClient(target_session, telethon_api_id, telethon_api_hash) as target_client:
        try:
            await target_client(JoinChannelRequest(debug_chat_id))
        except Exception as e:
            # If already a member or another non-critical error, print and continue.
            print(f"Target user join attempt: {e}")
        # 4. Target user sends a spam message with a unique hash.
        unique_hash = str(uuid.uuid4())
        spam_text = f"Spam test message {unique_hash}"
        spam_sent = await target_client.send_message(debug_chat_id, spam_text)
        spam_message_id = spam_sent.id

    # 5. Global admin sends the /spam command in reply.
    async with TelegramClient(admin_session, telethon_api_id, telethon_api_hash) as admin_client:
        await admin_client.send_message(debug_chat_id, "/spam", reply_to=spam_message_id)
        # Wait 60 seconds for the /spam command to be processed.
        await asyncio.sleep(60)

    # 6. Verify in the database that all logs for the unique hash are marked as spam.
    with session_scope() as session:
        logs = session.query(Message_Log).filter(
            Message_Log.chat_id == debug_chat_id,
            Message_Log.message_content.ilike(f"%{unique_hash}%")
        ).all()
        # Materialize only the needed data to avoid detached instances.
        logs_data = [
            {"id": log.id, "is_spam": log.is_spam, "manually_verified": log.manually_verified}
            for log in logs
        ]
    assert logs_data, f"No logs found for message containing {unique_hash}"
    for data in logs_data:
        assert data["is_spam"] is True, f"Log {data['id']} is not marked as spam."
        assert data["manually_verified"] is True, f"Log {data['id']} is not marked as manually verified."

    # 7. Verify that the original spam message has been deleted.
    async with TelegramClient(target_session, telethon_api_id, telethon_api_hash) as target_client:
        try:
            msgs = await target_client.get_messages(debug_chat_id, ids=spam_message_id)
            assert not msgs, "Spam message was not deleted from the chat."
        except errors.MessageIdInvalidError:
            # Expected if the message was deleted.
            pass

    # 8. Global admin sends the /unspam command in reply.
    async with TelegramClient(admin_session, telethon_api_id, telethon_api_hash) as admin_client:
        await admin_client.send_message(debug_chat_id, "/unspam", reply_to=spam_message_id)
        # Wait 60 seconds for the /unspam command to be processed.
        await asyncio.sleep(60)

    # 9. Target user re-joins the chat and sends a new message.
    async with TelegramClient(target_session, telethon_api_id, telethon_api_hash) as target_client:
        try:
            await target_client(JoinChannelRequest(debug_chat_id))
        except Exception as e:
            print(f"Target user rejoin attempt: {e}")
        rejoin_text = f"Rejoin test after unspam {str(uuid.uuid4())}"
        rejoin_msg = await target_client.send_message(debug_chat_id, rejoin_text)
        assert rejoin_msg, "Target user could not send a message after unspam."

    # 10. Verify in the DB that logs for the unique hash are updated (is_spam=False, manually_verified=True).
    with session_scope() as session:
        updated_logs = session.query(Message_Log).filter(
            Message_Log.chat_id == debug_chat_id,
            Message_Log.message_content.ilike(f"%{unique_hash}%")
        ).all()
        updated_logs_data = [
            {"id": log.id, "is_spam": log.is_spam, "manually_verified": log.manually_verified}
            for log in updated_logs
        ]
    assert updated_logs_data, f"No logs found for message containing {unique_hash} after unspam"
    for data in updated_logs_data:
        assert data["is_spam"] is False, f"Log {data['id']} is still marked as spam after unspam."
        assert data["manually_verified"] is True, f"Log {data['id']} is not marked as manually verified after unspam."

    # 11. Stop the bot application.
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    assert True, "tg_spam_unspam_flow integration test passed."
