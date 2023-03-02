from admin_log import admin_log
import os
import configparser
import telegram

import asyncio
import psycopg2
import psycopg2.extras

config = configparser.ConfigParser()
config_path = os.path.dirname(os.path.dirname(__file__)) + '/config/' #we need this trick to get path to config folder
config.read(config_path + 'settings.ini')
config.read(config_path + 'bot.ini')
config.read(config_path + 'db.ini')

admin_log(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = telegram.Bot(token=config['BOT']['KEY'])

async def status_update():
    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])

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
        print(error)
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