from admin_log import admin_log
import os
import configparser
from telegram import Bot
from telegram.ext import Application, MessageHandler, filters

from datetime import datetime
import psycopg2

config = configparser.ConfigParser()
config_path = os.path.dirname(os.path.dirname(__file__)) + '/config/' #we need this trick to get path to config folder
config.read(config_path + 'settings.ini')
config.read(config_path + 'bot.ini')
config.read(config_path + 'db.ini')

admin_log(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = Bot(config['BOT']['KEY'])

########################


async def tg_new_member(update, context):
    
    delete_NEW_CHAT_MEMBERS_message = config.getboolean('NEW_CHAT_MEMBERS', 'delete_NEW_CHAT_MEMBERS_message')
    
    if delete_NEW_CHAT_MEMBERS_message == True:
        await bot.delete_message(update.message.chat.id,update.message.id)

        admin_log(f"Joining message deleted from chat {update.message.chat.title} ({update.message.chat.id}) for user {update.message.from_user.username} ({update.message.from_user.id})")

async def wiretapping(update, context):
    #check if chat id is the same as in config
    #TODO: we need to rewrite all this to support multiple chats. May be we should add chat_id to users table
    try:
        if update.message.chat.id == int(config['BOT']['CHAT_ID']):
            if len(update.message.new_chat_members) > 0: #user added
                db_update_user(update.message.new_chat_members[0].id, update.message.new_chat_members[0].username, datetime.now())
            else:
                db_update_user(update.message.from_user.id, update.message.from_user.username, datetime.now())
            #admin_log(f"{update.message.from_user.username} ({update.message.from_user.id}): {update.message.text}")
    except Exception as e:
        admin_log(f"Error in wiretapping: {e}\n{update}")
        print(e)


def db_update_user(user_id, username, last_message_datetime):
    #TODO: we need to relocate this function to another location
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

    #delete new member message
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_new_member))

    #wiretapping
    application.add_handler(MessageHandler(filters.TEXT, wiretapping))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, wiretapping))

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()

#let's test how can we automate the deploy. We will push this to main first, then switch to to_heroku and merge and push.
#we are in dev branch now