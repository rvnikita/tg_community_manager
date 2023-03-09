import sys
sys.path.insert(0, '../') # add parent directory to the path
from admin_log import admin_log
import db_helper

import os
import configparser
import telegram

import asyncio
import psycopg2
import psycopg2.extras

config = configparser.ConfigParser()
config_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + '/config/' #we need this trick to get path to config folder
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
            try:
                chat_member = await bot.get_chat_member(config['BOT']['CHAT_ID'], user_row['id'])
                status = chat_member.status
                is_bot = chat_member.user.is_bot
            except (Exception, psycopg2.DatabaseError) as error:
                status = str(error)
                is_bot = 'NULL'

            if status != user_row['status']: #status has changed
                user_update_sql = f"UPDATE users set status = '{status}', is_bot = {is_bot} WHERE id = {user_row['id']}"
                print(user_update_sql)
                cur.execute(user_update_sql)
                conn.commit()
                admin_log(f"User @{user_row['username']} ({user_row['id']}) status changed to {status}", critical=True)

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