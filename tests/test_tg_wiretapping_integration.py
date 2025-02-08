import os
import uuid
import pytest
import asyncio

from telethon import TelegramClient
from telegram.ext import Application
from src.dispatcher import create_application  # your function returning a PTB Application
from src.db_helper import session_scope, Message_Log  # assuming these are accessible

@pytest.mark.asyncio
async def test_tg_integration_telethon():
    """
    This test manually initializes & starts the PTB Application, sends a message via Telethon
    with a unique random hash, then stops the bot and queries the DB to confirm that the
    message was logged.
    """
    # 1) Read environment variables
    telethon_api_id = int(os.getenv("TELETHON_API_ID", "0"))
    telethon_api_hash = os.getenv("TELETHON_API_HASH", "")
    debug_chat_id = int(os.getenv("ENV_INFO_CHAT_ID", "0"))
    
    # 2) Create the PTB application
    app: Application = create_application()  # must return an Application
    
    # 3) Manually initialize & start the application
    await app.initialize()
    await app.start()
    await app.updater.start_polling()  # non-blocking call to start polling
    
    # 4) Generate a unique hash and send a test message with that hash via Telethon
    unique_hash = str(uuid.uuid4())
    test_message_text = f"Hello from Telethon (manual start)! {unique_hash}"
    
    async with TelegramClient("test_session", telethon_api_id, telethon_api_hash) as client:
        await client.send_message(debug_chat_id, test_message_text)
        await asyncio.sleep(5)  # give the bot time to receive and process the message
    
    # 5) Cleanly stop the bot
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    
    # 6) Query the database to confirm the message was logged
    with session_scope() as session:
        # Adjust filter as necessary; here we use ILIKE for case-insensitive matching.
        logged_messages = session.query(Message_Log).filter(
            Message_Log.chat_id == debug_chat_id,
            Message_Log.message_content.ilike(f"%{unique_hash}%")
        ).all()
    
    assert logged_messages, f"Message with unique hash {unique_hash} was not logged."
    assert True, "Integration test with Telethon user completed."
