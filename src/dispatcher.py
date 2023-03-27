from src.admin_log import admin_log
import src.openai_helper as openai_helper
import src.chat_helper as chat_helper
import src.db_helper as db_helper
import src.config_helper as config_helper

import os
import configparser
from telegram import Bot
from telegram.ext import Application, MessageHandler, filters
from telegram.request import HTTPXRequest
import openai

from datetime import datetime
import psycopg2

config = config_helper.get_config()

admin_log(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = Bot(config['BOT']['KEY'],
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

########################

async def tg_thankyou(update, context):
    #category 0 - "thank you", 1 - "dislike"

    if update.message is not None \
            and update.message.reply_to_message is not None \
            and update.message.reply_to_message.from_user.id != update.message.from_user.id:
        chat = db_helper.session.query(db_helper.Chat).filter(db_helper.Chat.id == update.message.chat.id).first()
        #TODO:HIGH: check if we don't have like_words and dislike_words in config then we need to use default values
        like_words = chat.config['like_words']
        dislike_words = chat.config['dislike_words']

        for category, word_list in {'like_words': like_words, 'dislike_words': dislike_words}.items():
            for word in word_list:
                 #check without case if word in update message
                if word.lower() in update.message.text.lower():
                    user = db_helper.session.query(db_helper.User).filter(db_helper.User.id == update.message.reply_to_message.from_user.id).first()
                    if user is None:
                        user = db_helper.User(id=update.message.reply_to_message.from_user.id, first_name=update.message.reply_to_message.from_user.first_name, last_name=update.message.reply_to_message.from_user.last_name, username=update.message.reply_to_message.from_user.username)
                        db_helper.session.add(user)
                        db_helper.session.commit()

                    user_status = db_helper.session.query(db_helper.User_Status).filter(db_helper.User_Status.chat_id == update.message.chat.id, db_helper.User_Status.user_id == update.message.reply_to_message.from_user.id).first()
                    if user_status is None:
                        user_status = db_helper.User_Status(chat_id=update.message.chat.id, user_id=update.message.reply_to_message.from_user.id, rating=0)
                        db_helper.session.add(user_status)
                        db_helper.session.commit()

                    if category == "like_words":
                        user_status.rating += 1
                        rating_action = "increased"
                    elif category == "dislike_words":
                        user_status.rating -= 1
                        rating_action = "decreased"

                    db_helper.session.commit()


                    judge = db_helper.session.query(db_helper.User).filter(db_helper.User.id == update.message.from_user.id).first()
                    if judge is None:
                        judge = db_helper.User(id=update.message.from_user.id, name=update.message.from_user.first_name)
                        db_helper.session.add(judge)
                        db_helper.session.commit()

                    judge_status = db_helper.session.query(db_helper.User_Status).filter(db_helper.User_Status.chat_id == update.message.chat.id, db_helper.User_Status.user_id == update.message.from_user.id).first()
                    if judge_status is None:
                        judge_status = db_helper.User_Status(chat_id=update.message.chat.id, user_id=update.message.from_user.id, rating=0)
                        db_helper.session.add(judge_status)
                        db_helper.session.commit()

                    #TODO:HIGH: we need to check if we have name or username and use something that is not None

                    # This lines was written by GPT-4 to generate desirable output for different user input combinations:
                    # Output table for different user input combinations:
                    #   First name | Last name | Username   | ID   | `user_mention`
                    # --------------|-----------|------------|------|------------------------------
                    #   "Nikita"    | "Rvachev" | "rvnikita" | 123  | "Nikita Rvachev - @rvnikita"
                    #   "Nikita"    | "Rvachev" | None       | 123  | "Nikita Rvachev"
                    #   None        | None      | "rvnikita" | 123  | "@rvnikita"
                    #   "Nikita"    | None      | "rvnikita" | 123  | "Nikita - @rvnikita"
                    #   None        | "Rvachev" | "rvnikita" | 123  | "Rvachev - @rvnikita"
                    #   "Nikita"    | None      | None       | 123  | "Nikita"
                    #   None        | "Rvachev" | None       | 123  | "Rvachev"
                    #   None        | None      | None       | 123  | "123"
                    user_mention = ', '.join(filter(bool, [f"{user.first_name} {user.last_name} - @{user.username}" if user.first_name and user.last_name and user.username else f"{user.first_name} {user.last_name}" if user.first_name and user.last_name else f"@{user.username}" if user.username else str(user.id)]))
                    judge_mention = ', '.join(filter(bool, [f"{judge.first_name} {judge.last_name} - @{judge.username}" if judge.first_name and judge.last_name and judge.username else f"{judge.first_name} {judge.last_name}" if judge.first_name and judge.last_name else f"@{judge.username}" if judge.username else str(judge.id)]))


                    # user_mention = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"@{user.username}"
                    # judge_mention = f"{judge.first_name or ''} {judge.last_name or ''}".strip() or f"@{judge.username}"

                    text_to_send = f"{judge_mention} ({int(judge_status.rating)}) {rating_action} reputation of {user_mention} ({user_status.rating})"
                    await bot.send_message(chat_id=update.message.chat.id, text=text_to_send, reply_to_message_id=update.message.message_id)
                    admin_log(text_to_send + f" in chat {update.message.chat.id} ({update.message.chat.title})", critical=False)

                    db_helper.session.close()

                    return
    else:
        pass

async def tg_new_member(update, context):
    
    delete_NEW_CHAT_MEMBERS_message = config.getboolean('NEW_CHAT_MEMBERS', 'delete_NEW_CHAT_MEMBERS_message')
    
    if delete_NEW_CHAT_MEMBERS_message == True:
        await bot.delete_message(update.message.chat.id,update.message.id)

        admin_log(f"Joining message deleted from chat {update.message.chat.title} ({update.message.chat.id}) for user @{update.message.from_user.username} ({update.message.from_user.id})")

async def tg_update_user_status(update, context):
    #TODO: we need to rewrite all this to support multiple chats. May be we should add chat_id to user table
    if update.message is not None:
        config_update_user_status = chat_helper.get_chat(update.message.chat.id, "update_user_status")
        if config_update_user_status == None:
            admin_log(f"Skip: no config for chat {update.message.chat.id} ({update.message.chat.title})")
            return

        if config_update_user_status == True:
            if len(update.message.new_chat_members) > 0: #user added
                #TODO:HIGH: We need to rewrite this so we can also add full name
                db_update_user(update.message.new_chat_members[0].id, update.message.chat.id,  update.message.new_chat_members[0].username, datetime.now(), update.message.new_chat_members[0].first_name, update.message.new_chat_members[0].last_name)
            else:
                # TODO:HIGH: We need to rewrite this so we can also add full name
                db_update_user(update.message.from_user.id, update.message.chat.id, update.message.from_user.username, datetime.now(), update.message.from_user.first_name, update.message.from_user.last_name)
            #admin_log(f"{update.message.from_user.username} ({update.message.from_user.id}): {update.message.text}")


        #TODO: we need to separate this part of the code to separate funciton tg_openai_autorespond
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



def db_update_user(user_id, chat_id, username, last_message_datetime, first_name=None, last_name=None):
    #TODO: we need to relocate this function to another location
    try:
        if chat_id is None:
            admin_log(f"Debug: no chat_id for user {user_id} ({username}) last_message_datetime")

        # Update or insert user
        user = db_helper.session.query(db_helper.User).filter_by(id=user_id).first()
        if user:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
        else:
            user = db_helper.User(id=user_id, username=username, first_name=first_name, last_name=last_name)
            db_helper.session.add(user)

        # Update or insert user status
        user_status = db_helper.session.query(db_helper.User_Status).filter_by(user_id=user_id, chat_id=chat_id).first()
        if user_status:
            user_status.last_message_datetime = last_message_datetime
        else:
            user_status = db_helper.User_Status(user_id=user_id, chat_id=chat_id, last_message_datetime=last_message_datetime)
            db_helper.session.add(user_status)

        db_helper.session.commit()

    except Exception as error:
        admin_log(f"Error in file {__file__}: {error}", critical=True)
        db_helper.session.rollback()
    finally:
        db_helper.session.close()


def main() -> None:
    try:
        application = Application.builder().token(config['BOT']['KEY']).build()

        #delete new member message
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_new_member), group=1)

        #wiretapping
        application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.SUPERGROUP, tg_update_user_status), group=2) #filters.ChatType.SUPERGROUP to get only chat messages
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_update_user_status), group=2)

        # checking if user says thank you.
        application.add_handler(MessageHandler(filters.TEXT, tg_thankyou), group=3)

        # Start the Bot
        application.run_polling()
    except Exception as e:
        admin_log(f"Error in file {__file__}: {e}", critical=True)
if __name__ == '__main__':
    main()