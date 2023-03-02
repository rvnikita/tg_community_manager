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

async def warn_inactive():
    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])

        sql = "SELECT * FROM users WHERE last_message_datetime < NOW() - INTERVAL '60 days' AND last_message_datetime >= NOW() - INTERVAL '90 days' AND status IN ('member', 'administrator') AND username <> 'None';"
        cur = conn.cursor(cursor_factory = psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        #join all nicknames with attached @ before them in one string separated by comma and last with "и "
        joined_nicknames = ', '.join([f"@{row['username']}" for row in rows[:-1]]) + f" и @{rows[-1]['username']}"

        warn_text = "Список кандидатов-молчунов на выбывание в этом месяце " + joined_nicknames + ". Уже как минимум пару месяцев мы ничего от них не слышали :("

        await bot.send_message(chat_id=config['BOT']['CHAT_ID'], text=warn_text)

    except (Exception, psycopg2.DatabaseError) as error:
        admin_log(f"Error in file {__file__}: {error}", critical=True)
    finally:
        if conn is not None:
                conn.close()

async def delete_inactive():
    pass

    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])

        #we don't touch admins
        sql = "SELECT * FROM users WHERE last_message_datetime < NOW() - INTERVAL '90 days' AND status IN ('member') AND username <> 'None';"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        for row in rows:
            try:
                await bot.kick_chat_member(config['BOT']['CHAT_ID'], row['id'])
                admin_log(f"User @{row['username']} ({row['id']}) was kicked for inactivity")
            except (Exception, psycopg2.DatabaseError) as error:
                admin_log(f"Error in file {__file__}: {error}", critical=True)

    except (Exception, psycopg2.DatabaseError) as error:
        admin_log(f"Error in file {__file__}: {error}", critical=True)
    finally:
        if conn is not None:
            conn.close()


async def main() -> None:
    try:
        await warn_inactive()
        await delete_inactive()
    except Exception as e:
        admin_log(f"Error in {__file__}: {e}", critical=True)

if __name__ == "__main__":
    asyncio.run(main())