# auth_telethon.py

import asyncio
from telethon import TelegramClient
import os
from dotenv import load_dotenv

load_dotenv("config/.env")

# These can come from env vars, config files, etc.
API_ID = int(os.getenv("TELETHON1_API_ID"))
API_HASH = os.getenv("TELETHON1_API_HASH")
PHONE_NUMBER = os.getenv("TELETHON1_PHONE_NUMBER")

SESSION_NAME = "TELETHON1"  # or another name you want

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    print(f"Starting Telethon client (session='{SESSION_NAME}')...")
    await client.start()
    print("Session saved. You won't need to log in again for this session file.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
