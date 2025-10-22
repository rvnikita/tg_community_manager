import os
import uuid
import pytest
import asyncio

from telethon import TelegramClient
from telegram.ext import Application
from src.dispatcher import create_application
from src.helpers.db_helper import session_scope, Message_Log


@pytest.mark.asyncio
async def test_basic_message_logging():
    """
    Basic test to verify that when a user sends a message to the chat,
    the bot receives it and logs it to the database.

    Test flow:
    1. Start the bot application
    2. Send a message with a unique identifier via Telethon
    3. Wait for the bot to process the message
    4. Stop the bot application
    5. Query the database to verify the message was logged
    """
    # Read environment variables for Telethon client
    telethon_api_id = int(os.getenv("TELETHON1_API_ID", "0"))
    telethon_api_hash = os.getenv("TELETHON1_API_HASH", "")
    telethon_session = os.getenv("TELETHON1_SESSION", "TELETHON1")
    debug_chat_id = int(os.getenv("ENV_INFO_CHAT_ID", "0"))

    # Create and start the bot application
    app: Application = create_application()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Generate a unique identifier for this test message
    unique_id = str(uuid.uuid4())
    test_message = f"Test message for basic logging: {unique_id}"

    # Send the test message via Telethon
    async with TelegramClient(telethon_session, telethon_api_id, telethon_api_hash) as client:
        await client.send_message(debug_chat_id, test_message)
        # Wait for the bot to process the message
        await asyncio.sleep(5)

    # Stop the bot application
    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    # Verify the message was logged in the database
    with session_scope() as session:
        logged_message = session.query(Message_Log).filter(
            Message_Log.chat_id == debug_chat_id,
            Message_Log.message_content.ilike(f"%{unique_id}%")
        ).first()

    # Assert that the message was found in the database
    assert logged_message is not None, f"Message with unique ID {unique_id} was not found in the database"
    assert unique_id in logged_message.message_content, "Logged message content does not contain the unique ID"
    print(f"✓ Message successfully logged with ID: {logged_message.id}")
