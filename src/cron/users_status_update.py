import sys
sys.path.insert(0, '../') # add parent directory to the path
from src.admin_log import admin_log
import src.db_helper as db_helper
import src.chat_helper as chat_helper
import src.config_helper as config_helper

import os
import telegram

import asyncio
import psycopg2
import psycopg2.extras

config = config_helper.get_config()

admin_log(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = telegram.Bot(token=config['BOT']['KEY'])

async def chat_name_update():
    conn = None
    try:
        conn = db_helper.connect()
        sql = "SELECT * FROM tg_chat where chat_name = '' or chat_name is NULL"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        for row in rows:
            try:
                chat = await bot.get_chat(row['id'])
                title = chat.title
            except Exception as error:
                title = error

            try:
                update_sql = f"UPDATE tg_chat set chat_name = '{title}' WHERE id = {row['id']}"
                cur.execute(update_sql)
                conn.commit()
            except (Exception, psycopg2.DatabaseError) as error:
                admin_log(f"Error in file {__file__}: {error}", critical=True)
    except (Exception, psycopg2.DatabaseError) as error:
        admin_log(f"Error in file {__file__}: {error}", critical=True)


async def status_update():
    #FIXME: we need to rewrite this with new structure of user and user_status tables
    #TODO:HIGH: rewrite with ORM and update fullname for user
    conn = None
    try:
        conn = db_helper.connect()

        sql = "SELECT * FROM tg_user"
        cur = conn.cursor(cursor_factory = psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        for user_row in rows:
            print(user_row['id'])
            sql = f"SELECT * FROM tg_user_status WHERE user_id = {user_row['id']}"
            cur.execute(sql)
            user_status_rows = cur.fetchall()
            for user_status_row in user_status_rows:
                try:
                    print(f"chat_id={user_status_row['chat_id']}, user_id={user_row['id']}")
                    chat_member = await bot.get_chat_member(user_status_row['chat_id'], user_row['id'])
                    status = chat_member.status
                    is_bot = chat_member.user.is_bot
                except Exception as error:
                    # admin_log(f"Error in file {__file__}: {error}", critical=True)
                    status = str(error)
                    is_bot = 'NULL'

                if status != user_status_row['status']: #status has changed
                    user_update_sql = f"UPDATE tg_user_status set status = '{status}' WHERE user_id = {user_row['id']} AND chat_id = {user_status_row['chat_id']}"
                    print(user_update_sql)
                    cur.execute(user_update_sql)
                    conn.commit()

                    try:
                        chat = await bot.get_chat(user_status_row['chat_id'])
                        title = chat.title
                    except Exception as error:
                        title = "Not found"


                    config_update_user_status_critical = chat_helper.get_chat(user_status_row['chat_id'], "update_user_status_critical")
                    #TODO:MED: add "ban and delete" button in log
                    admin_log(f"User @{user_row['username']} ({user_row['id']}) in {title} ({user_status_row['chat_id']}) status changed to {status}", critical=config_update_user_status_critical)

        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        admin_log(f"Error in file {__file__}: {error}", critical=True)
    finally:
        if conn is not None:
                conn.close()

async def main() -> None:
    try:
        await chat_name_update()
        await status_update()
    except Exception as e:
        admin_log(f"Error in file {__file__}: {e}", critical=True)

if __name__ == "__main__":
    asyncio.run(main())