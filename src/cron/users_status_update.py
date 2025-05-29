import sys
sys.path.insert(0, '../')  # add parent directory to the path
import src.helpers.db_helper as db_helper
import src.helpers.chat_helper as chat_helper
import src.helpers.logging_helper as logging_helper

import os
import telegram
import traceback
from telegram.request import HTTPXRequest
from telegram.error import BadRequest, Forbidden

import asyncio
import psycopg2
import psycopg2.extras

logger = logging_helper.get_logger()

logger.info(f"Starting {__file__} in {os.getenv('ENV_BOT_MODE')} mode at {os.uname()}")

bot = telegram.Bot(token=os.getenv('ENV_BOT_KEY'),
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
    logger.info("Starting status update cron script")

    updates = []

    with db_helper.connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = "SELECT id FROM tg_user ORDER BY RANDOM() LIMIT 1000"
            cur.execute(sql)
            user_rows = cur.fetchall()
            user_ids = [row['id'] for row in user_rows]
            user_dict = {row['id']: row.get('username', '') for row in user_rows}

            user_status_sql = "SELECT * FROM tg_user_status WHERE user_id = ANY(%s)"
            cur.execute(user_status_sql, (user_ids,))
            user_status_rows = cur.fetchall()

            for user_status_row in user_status_rows:
                user_display = user_dict.get(user_status_row['user_id']) or user_status_row['user_id']
                chat_id = user_status_row['chat_id']
                user_id = user_status_row['user_id']
                try:
                    chat_member = await bot.get_chat_member(chat_id, user_id)
                    status = chat_member.status

                    if status != user_status_row['status']:
                        updates.append((status, user_id, chat_id))
                        logger.debug(f"(get_chat_member) Status change detected for user {'@' if not (isinstance(user_display, int) or user_display.isdigit()) else ''}{user_display} in chat {chat_id} to {status}")
                except BadRequest as bad_request_error:
                    error_message = str(bad_request_error)
                    where = f"(get_chat_member, chat_id={chat_id}, user_id={user_id})"
                    if "User not found" in error_message:
                        updates.append(("User not found", user_id, chat_id))
                        logger.debug(f"{where} User not found: {error_message}")
                    elif "Chat not found" in error_message:
                        logger.debug(f"{where} Chat not found: {error_message}")
                    elif "Member not found" in error_message:
                        updates.append(("Member not found", user_id, chat_id))
                        logger.debug(f"{where} Member not found: {error_message}")
                    elif "Participant_id_invalid" in error_message:
                        updates.append(("Participant ID invalid", user_id, chat_id))
                        logger.debug(f"{where} Participant ID invalid: {error_message}")
                    elif "Chat_admin_required" in error_message:
                        logger.debug(f"{where} Chat_admin_required - not an error: {error_message}")
                    else:
                        logger.error(f"{where} BadRequest error: {traceback.format_exc()}")
                except Forbidden as forbidden_error:
                    where = f"(get_chat_member, chat_id={chat_id}, user_id={user_id})"
                    logger.debug(f"{where} Forbidden: {forbidden_error}")
                except Exception:
                    where = f"(get_chat_member, chat_id={chat_id}, user_id={user_id})"
                    logger.error(f"{where} Exception: {traceback.format_exc()}")

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
