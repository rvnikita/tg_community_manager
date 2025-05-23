#!/usr/bin/env python3
import sys
sys.path.insert(0, '../')  # add parent directory to the path


import os
import asyncio

import requests
from telethon import TelegramClient

import dotenv
import logging_helper

dotenv.load_dotenv("config/.env")
logger = logging_helper.get_logger()

async def health_check():
    client = TelegramClient(
        os.getenv("CAS_TELETHON_SESSION_NAME", "health_check"),
        int(os.getenv("CAS_TELETHON_API_ID")),
        os.getenv("CAS_TELETHON_API_HASH"),
    )
    await client.start(os.getenv("CAS_TELETHON_PHONE_NUMBER"))
    me = await client.get_me()
    logger.info(f"Logged in as {me.username} (id={me.id})")

    try:
        async with client.conversation(os.getenv("ENV_BOT_USERNAME"), timeout=10) as conv:
            await conv.send_message("/ping")
            resp = await conv.get_response()
            text = resp.raw_text or ""
            if "Pong" in text:
                logger.info("🏓 Ping-Pong: Pong received")
                await client.disconnect()
                return
            logger.error(f"❌🏓 Ping-Pong: Unexpected reply: {text!r}")
    except asyncio.TimeoutError:
        logger.error("❌🏓 Ping-Pong: Timeout waiting for Pong")
    except Exception as e:
        logger.error(f"❌🏓 Ping-Pong: Error during health check: {e}")

    # no Pong → restart Heroku
    url = f"https://api.heroku.com/apps/{os.getenv('HEROKU_APP_NAME')}/dynos"
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Authorization": f"Bearer {os.getenv('HEROKU_API_KEY')}"
    }
    resp = requests.delete(url, headers=headers)
    if resp.status_code == 202:
        logger.info("Heroku dynos restarted")
    else:
        logger.error(f"Failed to restart Heroku ({resp.status_code}): {resp.text}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(health_check())
