from code.admin_log import admin_log
import os
import configparser
from telegram.ext import Application, MessageHandler, filters

from datetime import datetime
import psycopg2

config = configparser.ConfigParser()
config.read('config/settings.ini')
config.read('config/bot.ini')
config.read('config/db.ini')

admin_log(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

async def wiretapping(update, context):
    if len(update.message.new_chat_members) > 0: #user added
        db_update_user(update.message.new_chat_members[0].id, update.message.new_chat_members[0].username, datetime.now())
    else:
        db_update_user(update.message.from_user.id, update.message.from_user.username, datetime.now())
    #admin_log(f"{update.message.from_user.username} ({update.message.from_user.id}): {update.message.text}")


def db_update_user(user_id, username, last_message_datetime):
    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])
                                          
        sql = f"""
        UPDATE users SET username='{username}', last_message_datetime='{last_message_datetime}' WHERE id={user_id};
        INSERT INTO users (id, username, last_message_datetime)
               SELECT {user_id}, '{username}', '{last_message_datetime}'
               WHERE NOT EXISTS (SELECT 1 FROM users WHERE id={user_id});
        """                                  
        # create a new cursor
        cur = conn.cursor()
        # execute the INSERT statement
        cur.execute(sql)
        # commit the changes to the database
        conn.commit()
        # close communication with the database
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
                conn.close()
                
def main() -> None:
    application = Application.builder().token(config['BOT']['KEY']).build()
    
    # application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, echo)) #track new users
    
    application.add_handler(MessageHandler(filters.TEXT, wiretapping))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, wiretapping))

    # Start the Bot
    application.run_polling()
        

if __name__ == '__main__':
    main()