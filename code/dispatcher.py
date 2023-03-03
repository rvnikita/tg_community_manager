from admin_log import admin_log
import openai_helper

import os
import configparser
from telegram import Bot
from telegram.ext import Application, MessageHandler, filters
import openai

from datetime import datetime
import psycopg2

config = configparser.ConfigParser()
config_path = os.path.dirname(os.path.dirname(__file__)) + '/config/' #we need this trick to get path to config folder
config.read(config_path + 'settings.ini')
config.read(config_path + 'bot.ini')
config.read(config_path + 'openai.ini')
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
    #TODO: we need to rewrite all this to support multiple chats. May be we should add chat_id to users table
    if update.message is not None:
        # check if chat id is the same as in config
        if update.message.chat.id == int(config['BOT']['CHAT_ID']):
            if len(update.message.new_chat_members) > 0: #user added
                db_update_user(update.message.new_chat_members[0].id, update.message.new_chat_members[0].username, datetime.now())
            else:
                db_update_user(update.message.from_user.id, update.message.from_user.username, datetime.now())
            #admin_log(f"{update.message.from_user.username} ({update.message.from_user.id}): {update.message.text}")

        if update.message.chat.id == -1001588101140: #O1
        # if update.message.chat.id == -1001688952630:  # debug
            #TODO: we need to support multiple chats, settings in db etc

            #Let's here check if we know an answer for a question and send it to user
            openai.api_key = config['OPENAI']['KEY']

            messages = [
                {"role": "system",
                 "content": f"Answer only yes or no"},
                {"role": "user", "content": f"Is this a question: \"{update.message.text}\""}
            ]

            response = openai.ChatCompletion.create(
                model=config['OPENAI']['COMPLETION_MODEL'],
                messages=messages,
                temperature=float(config['OPENAI']['TEMPERATURE']),
                max_tokens=int(config['OPENAI']['MAX_TOKENS']),
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0
            )

            #check if response.choices[0].message.content contains "yes" without case sensitivity
            if "yes" in response.choices[0].message.content.lower():
                rows = openai_helper.get_nearest_vectors(update.message.text, 0)

                admin_log("Question detected " + update.message.text, critical=False)

                if len(rows) > 0:
                    admin_log("Vectors detected " + str(rows) + str(rows[0]['similarity']), critical=False)

                    #TODO this is a debug solution to skip questions with high similarity
                    if rows[0]['similarity'] < float(config['OPENAI']['SIMILARITY_THRESHOLD']):
                        admin_log("Skip, similarity=" + str(rows[0]['similarity']) + f" while threshold={config['OPENAI']['SIMILARITY_THRESHOLD']}", critical=False)
                        return #skip this message

                    messages = [
                        {"role": "system",
                         "content": f"Answer in one Russian message based on user question and embedding vectors. Do not mention embedding. Be applicable and short."},
                        {"role": "user", "content": f"\"{update.message.text}\""}
                    ]

                    for i in range(len(rows)):
                        messages.append({"role": "system", "content": f"Embedding Title {i}: {rows[i]['title']}\n Embedding Body {i}: {rows[i]['body']}"})

                    response = openai.ChatCompletion.create(
                        model=config['OPENAI']['COMPLETION_MODEL'],
                        messages=messages,
                        temperature=float(config['OPENAI']['TEMPERATURE']),
                        max_tokens=int(config['OPENAI']['MAX_TOKENS']),
                        top_p=1,
                        frequency_penalty=0,
                        presence_penalty=0
                    )
                    await bot.send_message(update.message.chat.id, response.choices[0].message.content + f" ({rows[0]['similarity']:.2f})", reply_to_message_id=update.message.message_id)

                    #resend update.message to admin
                    await bot.forward_message(config['BOT']['ADMIN_ID'], update.message.chat.id, update.message.message_id)
                    await bot.send_message(config['BOT']['ADMIN_ID'], response.choices[0].message.content + f" ({rows[0]['similarity']:.2f})", disable_web_page_preview=True)



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
        admin_log(f"Error in file {__file__}: {error}", critical=True)
    finally:
        if conn is not None:
            conn.close()


def main() -> None:
    try:
        application = Application.builder().token(config['BOT']['KEY']).build()

        #delete new member message
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_new_member))

        #wiretapping
        application.add_handler(MessageHandler(filters.TEXT, wiretapping))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, wiretapping))

        # Start the Bot
        application.run_polling()
    except Exception as e:
        admin_log(f"Error in file {__file__}: {e}", critical=True)
if __name__ == '__main__':
    main()