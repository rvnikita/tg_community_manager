# tests/test_tg_integration_telethon.py

import os
import pytest
import asyncio

from telethon import TelegramClient
from telegram.ext import Application
from src.dispatcher import create_application  # your function returning a PTB Application

@pytest.mark.asyncio
async def test_tg_integration_telethon():
    """
    This test manually initializes & starts the PTB Application, starts polling,
    sends a message via Telethon, and then stops the bot. It avoids run_polling(),
    which tries to manage its own event loop and conflicts with pytest-asyncio.
    """

    # 1) Read environment variables
    telethon_api_id = int(os.getenv("TELETHON_API_ID", "0"))
    telethon_api_hash = os.getenv("TELETHON_API_HASH", "")
    phone_number = os.getenv("TELETHON_PHONE_NUMBER", "")
    debug_chat_id = int(os.getenv("ENV_INFO_CHAT_ID", "0"))

    # 2) Create the PTB application
    app: Application = create_application()  # must return an Application

    # 3) Manually initialize & start the application
    #    instead of app.run_polling()
    await app.initialize()
    await app.start()
    # If your app uses an Updater under the hood:
    await app.updater.start_polling()  # non-blocking call to start polling

    # 4) Use Telethon to send a test message as a "real user"
    async with TelegramClient("test_session", telethon_api_id, telethon_api_hash) as client:
        # If not authorized, you'd sign in once in a separate script or do:
        # if not await client.is_user_authorized():
        #     await client.send_code_request(phone_number)
        #     code = input("Enter the code: ")
        #     await client.sign_in(phone_number, code)

        await client.send_message(debug_chat_id, "Hello from Telethon (manual start)!")
        await asyncio.sleep(5)  # give the bot time to receive & handle

    # 5) Cleanly stop the bot
    #    This mirrors what run_polling() does internally upon shutdown
    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    # After stopping, you can do any DB assertions/log checks here.
    assert True, "Integration test with Telethon user completed."
