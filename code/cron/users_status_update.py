import sys
sys.path.insert(0, '../') # add parent directory to the path
from admin_log import admin_log
import db_helper
import config_helper

import os
import configparser
import telegram

import asyncio
import psycopg2
import psycopg2.extras

config = configparser.ConfigParser()
config_path = os.path.dirname(os.path.dirname(__file__)) + '/../config/' #we need this trick to get path to config folder
config.read(config_path + 'settings.ini')
config.read(config_path + 'bot.ini')
config.read(config_path + 'db.ini')

admin_log(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = telegram.Bot(token=config['BOT']['KEY'])

async def status_update():
    #FIXME: we need to rewrite this with new structure of users and user_status tables
    conn = None
    try:
        conn = db_helper.connect()

        sql = "SELECT * FROM users"
        cur = conn.cursor(cursor_factory = psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        for user_row in rows:
            print(user_row['id'])
            sql = f"SELECT * FROM users_status WHERE user_id = {user_row['id']}"
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
                    user_update_sql = f"UPDATE users_status set status = '{status}' WHERE user_id = {user_row['id']} AND chat_id = {user_status_row['chat_id']}"
                    print(user_update_sql)
                    cur.execute(user_update_sql)
                    conn.commit()

                    try:
                        chat = await bot.get_chat(user_status_row['chat_id'])
                        title = chat.title
                    except Exception as error:
                        title = "Not found"


                    config = config_helper.get_config(user_status_row['chat_id'])
                    admin_log(f"User @{user_row['username']} ({user_row['id']}) in {title} ({user_status_row['chat_id']}) status changed to {status}", critical=config['update_user_status_critical'])

        conn.commit()
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        admin_log(f"Error in file {__file__}: {error}", critical=True)
    finally:
        if conn is not None:
                conn.close()

async def main() -> None:
    try:
        await status_update()
    except Exception as e:
        admin_log(f"Error in file {__file__}: {e}", critical=True)

if __name__ == "__main__":
    asyncio.run(main())