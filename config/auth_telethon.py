import asyncio
import os
from dotenv import load_dotenv

from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv("config/.env")

API_ID = int(os.getenv("TELETHON1_API_ID"))
API_HASH = os.getenv("TELETHON1_API_HASH")
PHONE_NUMBER = os.getenv("TELETHON1_PHONE_NUMBER")

async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        await client.start(PHONE_NUMBER)
        session_string = client.session.save()
        print("Session string (save this to your .env as TELETHON1_SESSION_STRING):")
        print(session_string)

if __name__ == "__main__":
    asyncio.run(main())
