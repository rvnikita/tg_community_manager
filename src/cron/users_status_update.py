import sys
sys.path.insert(0, '../')  # add parent directory to the path
import src.db_helper as db_helper
import src.chat_helper as chat_helper
import src.config_helper as config_helper
import src.logging_helper as logging_helper

import os
import telegram
import traceback
from telegram.request import HTTPXRequest

import asyncio
import psycopg2
import psycopg2.extras

config = config_helper.get_config()

logger = logging_helper.get_logger()

logger.info(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = telegram.Bot(token=config['BOT']['KEY'],
                   request=HTTPXRequest(http_version="1.1"),  # we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
                   get_updates_request=HTTPXRequest(http_version="1.1"))  # we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556


async def chat_name_update():
    with db_helper.connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = "SELECT * FROM tg_chat where chat_name = '' or chat_name is NULL"
            cur.execute(sql)
            rows = cur.fetchall()

            for row in rows:
                try:
                    chat = await bot.get_chat(row['id'])
                    title = chat.title
                    update_sql = "UPDATE tg_chat set chat_name = %s WHERE id = %s"
                    cur.execute(update_sql, (title, row['id']))
                except Exception as error:
                    logger.error(f"Error: {traceback.format_exc()}")
            conn.commit()


async def status_update():
    updates = []  # A list to store all updates

    with db_helper.connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = "SELECT * FROM tg_user ORDER BY RANDOM() LIMIT 150"
            cur.execute(sql)
            user_rows = cur.fetchall()

            for user_row in user_rows:
                user_status_sql = "SELECT * FROM tg_user_status WHERE user_id = %s"
                cur.execute(user_status_sql, (user_row['id'],))
                user_status_rows = cur.fetchall()

                for user_status_row in user_status_rows:
                    try:
                        chat_member = await bot.get_chat_member(user_status_row['chat_id'], user_row['id'])
                        status = chat_member.status

                        # Add to updates only if the status has changed
                        if status != user_status_row['status']:
                            updates.append((status, user_row['id'], user_status_row['chat_id']))
                            logger.info(f"Status change detected for user @{user_row['username']} ({user_row['id']}) in chat {user_status_row['chat_id']} to {status}")
                    except Exception as error:
                        logger.error(f"Error fetching chat member status: {traceback.format_exc()}")

            # Batch update all statuses
            if updates:
                user_update_sql = "UPDATE tg_user_status set status = %s WHERE user_id = %s AND chat_id = %s"
                cur.executemany(user_update_sql, updates)

            conn.commit()


async def main() -> None:
    try:
        await chat_name_update()
        await status_update()
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")


if __name__ == "__main__":
    asyncio.run(main())
