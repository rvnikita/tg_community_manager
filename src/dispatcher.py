import src.logging_helper as logging
import src.openai_helper as openai_helper
import src.chat_helper as chat_helper
import src.db_helper as db_helper
import src.config_helper as config_helper
import src.user_helper as user_helper

import os
import configparser
from telegram import Bot
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ChatJoinRequestHandler
from telegram.request import HTTPXRequest
import openai
import traceback


from datetime import datetime
import psycopg2

config = config_helper.get_config()

logger = logging.get_logger()

logger.info(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = Bot(config['BOT']['KEY'],
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

########################

async def send_message_to_admin(bot, chat_id, text: str):
    chat_administrators = await bot.get_chat_administrators(chat_id)

    for admin in chat_administrators:
        if admin.user.is_bot == True: #don't send to bots
            continue
        try:
            await bot.send_message(chat_id=admin.user.id, text=text)
        except Exception as error:
            logger.error(f"Error: {traceback.format_exc()}")

async def tg_report_reset(update, context):
    with db_helper.session_scope() as db_session:
        #TODO:HIGH: this command reset all reports for this user. It could work when it is replied to message or followed by nickname. It could be done only by chat admin.
        chat_id = update.effective_chat.id
        message = update.message

        chat_administrators = await bot.get_chat_administrators(chat_id)
        is_admin = False

        for admin in chat_administrators:
            if admin.user.id == message.from_user.id:
                is_admin = True
                break

        if not is_admin:
            bot.send_message(chat_id=chat_id, text="You are not an admin of this chat.")
            return

        if message.reply_to_message:
            reported_user_id = message.reply_to_message.from_user.id
        else:
            #we need to take user nickname and then find user_id
            #TODO:HIGH: implement this
            return

        reports = db_session.query(db_helper.Report).filter(db_helper.Report.reported_user_id == reported_user_id).all()
        for report in reports:
            db_session.delete(report)

        db_session.commit()

        bot.send_message(chat_id=chat_id, text="Reports for this user were reset.")


async def tg_report(update, context):
    with db_helper.session_scope() as db_session:
        chat_id = update.effective_chat.id

        message = update.message

        if message.reply_to_message:
            number_of_reports_to_warn = int(chat_helper.get_chat_config(chat_id, 'number_of_reports_to_warn'))
            number_of_reports_to_ban = int(chat_helper.get_chat_config(chat_id, 'number_of_reports_to_ban'))

            reported_message_id = message.reply_to_message.message_id
            reported_user_id = message.reply_to_message.from_user.id
            reporting_user_id = message.from_user.id

            # Check if the reported user is an admin of the chat
            chat_administrators = await bot.get_chat_administrators(chat_id)
            for admin in chat_administrators:
                if admin.user.id == reported_user_id:
                    await bot.send_message(chat_id=chat_id, text="You cannot report an admin.")
                    return

            # Check if the user has already been warned by the same reporter
            existing_report = db_session.query(db_helper.Report).filter(
                db_helper.Report.chat_id == chat_id,
                db_helper.Report.reported_user_id == reported_user_id,
                db_helper.Report.reporting_user_id == reporting_user_id
            ).first()

            if not existing_report or reporting_user_id in [admin.user.id for admin in chat_administrators]:
                # Add report to the database
                report = db_helper.Report(
                    reported_user_id=reported_user_id,
                    reporting_user_id=reporting_user_id,
                    reported_message_id=reported_message_id,
                    chat_id=chat_id
                )
                db_session.add(report)
                db_session.commit()
            else:
                await bot.send_message(chat_id=chat_id, text="You have already reported this user.")
                return

            # Count unique reports for the reported user in the chat
            report_count = db_session.query(db_helper.Report).filter(
                db_helper.Report.chat_id == chat_id,
                db_helper.Report.reported_user_id == reported_user_id
            ).count()

            reported_user_mention = user_helper.get_user_mention(reported_user_id)
            reporting_user_mention = user_helper.get_user_mention(reporting_user_id)

            await send_message_to_admin(bot, chat_id, f"User {reporting_user_mention} reported {reported_user_mention} in chat {chat_id}. Total reports: {report_count}. \nReported message: {message.reply_to_message.text}")
            await bot.send_message(chat_id=chat_id, text=f"User {reported_user_mention} has been reported {report_count} times.")

            if report_count >= number_of_reports_to_ban:
                await chat_helper.delete_message(bot, chat_id, reported_message_id)
                await chat_helper.ban_user(bot, chat_id, reported_user_id)
                await bot.send_message(chat_id=chat_id, text=f"User {reported_user_mention} has been banned due to {report_count} reports.")
                await send_message_to_admin(bot, chat_id, f"User {reported_user_mention} has been banned in chat {chat_id} due to {report_count} reports.")

                return #we don't need to warn and mute user if he is banned

            if report_count >= number_of_reports_to_warn:
                await chat_helper.warn_user(bot, chat_id, reported_user_id)
                await chat_helper.mute_user(bot, chat_id, reported_user_id)
                await bot.send_message(chat_id=chat_id, text=f"User {reported_user_mention} has been warned and muted due to {report_count} reports.")
                await send_message_to_admin(bot, chat_id, f"User {reported_user_mention} has been warned and muted in chat {chat_id} due to {report_count} reports.")



async def tg_thankyou(update, context):
    #category 0 - "thank you", 1 - "dislike"

    with db_helper.session_scope() as db_session:

        if update.message is not None \
                and update.message.reply_to_message is not None \
                and update.message.reply_to_message.from_user.id != update.message.from_user.id:

            # there is a strange behaviour when user send message in topic Telegram show it as a reply to forum_topic_created invisible message. We don't need to process it
            if update.message.reply_to_message.forum_topic_created is not None:
                return

            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == update.message.chat.id).first()
            #TODO:HIGH: check if we don't have like_words and dislike_words in config then we need to use default values
            like_words = chat.config['like_words']
            dislike_words = chat.config['dislike_words']

            for category, word_list in {'like_words': like_words, 'dislike_words': dislike_words}.items():
                for word in word_list:
                     #check without case if word in update message
                    if word.lower() in update.message.text.lower():
                        user = db_session.query(db_helper.User).filter(db_helper.User.id == update.message.reply_to_message.from_user.id).first()
                        if user is None:
                            user = db_helper.User(id=update.message.reply_to_message.from_user.id, first_name=update.message.reply_to_message.from_user.first_name, last_name=update.message.reply_to_message.from_user.last_name, username=update.message.reply_to_message.from_user.username)
                            db_session.add(user)
                            db_session.commit()

                        user_status = db_session.query(db_helper.User_Status).filter(db_helper.User_Status.chat_id == update.message.chat.id, db_helper.User_Status.user_id == update.message.reply_to_message.from_user.id).first()
                        if user_status is None:
                            user_status = db_helper.User_Status(chat_id=update.message.chat.id, user_id=update.message.reply_to_message.from_user.id, rating=0)
                            db_session.add(user_status)
                            db_session.commit()

                        if category == "like_words":
                            user_status.rating += 1
                            rating_action = "increased"
                        elif category == "dislike_words":
                            user_status.rating -= 1
                            rating_action = "decreased"

                        db_session.commit()


                        judge = db_session.query(db_helper.User).filter(db_helper.User.id == update.message.from_user.id).first()
                        if judge is None:
                            judge = db_helper.User(id=update.message.from_user.id, name=update.message.from_user.first_name)
                            db_session.add(judge)
                            db_session.commit()

                        judge_status = db_session.query(db_helper.User_Status).filter(db_helper.User_Status.chat_id == update.message.chat.id, db_helper.User_Status.user_id == update.message.from_user.id).first()
                        if judge_status is None:
                            judge_status = db_helper.User_Status(chat_id=update.message.chat.id, user_id=update.message.from_user.id, rating=0)
                            db_session.add(judge_status)
                            db_session.commit()

                        #TODO:HIGH: we need to check if we have name or username and use something that is not None


                        user_mention = user_helper.get_user_mention(user.id)
                        judge_mention = user_helper.get_user_mention(judge.id)

                        text_to_send = f"{judge_mention} ({int(judge_status.rating)}) {rating_action} reputation of {user_mention} ({user_status.rating})"
                        await bot.send_message(chat_id=update.message.chat.id, text=text_to_send, reply_to_message_id=update.message.message_id)
                        logger.info(text_to_send + f" in chat {update.message.chat.id} ({update.message.chat.title})")

                        db_session.close()

                        return
        else:
            pass

async def tg_join_request(update, context):
    try:
        welcome_message = chat_helper.get_chat_config(update.effective_chat.id, "welcome_message")

        if welcome_message is not None and welcome_message != "":
            await bot.send_message(update.effective_user.id, welcome_message, disable_web_page_preview=True)
            logger.info(f"Welcome message sent to user {update.effective_user.id} in chat {update.effective_chat.id} ({update.effective_chat.title})")

        chat_join_request = update.chat_join_request

        # Automatically approve the join request
        await chat_join_request.approve()


    except Exception as e:
        chat_join_request = update.chat_join_request
        # Automatically approve the join request
        await chat_join_request.approve()

        logger.error(f"Error: {traceback.format_exc()}")

async def tg_new_member(update, context):
    try:
        new_user_id = update.message.api_kwargs['new_chat_participant']['id']

        delete_NEW_CHAT_MEMBERS_message = config.getboolean('NEW_CHAT_MEMBERS', 'delete_NEW_CHAT_MEMBERS_message')

        if delete_NEW_CHAT_MEMBERS_message == True:
            await bot.delete_message(update.message.chat.id,update.message.id)

            logger.info(f"Joining message deleted from chat {update.message.chat.title} ({update.message.chat.id}) for user @{update.message.from_user.username} ({update.message.from_user.id})")

    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")

async def tg_update_user_status(update, context):
    try:
        #TODO: we need to rewrite all this to support multiple chats. May be we should add chat_id to user table
        if update.message is not None:
            config_update_user_status = chat_helper.get_chat_config(update.message.chat.id, "update_user_status")
            if config_update_user_status == None:
                logger.info(f"Skip: no config for chat {update.message.chat.id} ({update.message.chat.title})")
                return

            if config_update_user_status == True:
                if len(update.message.new_chat_members) > 0: #user added
                    #TODO:HIGH: We need to rewrite this so we can also add full name
                    db_update_user(update.message.new_chat_members[0].id, update.message.chat.id,  update.message.new_chat_members[0].username, datetime.now(), update.message.new_chat_members[0].first_name, update.message.new_chat_members[0].last_name)
                else:
                    # TODO:HIGH: We need to rewrite this so we can also add full name
                    db_update_user(update.message.from_user.id, update.message.chat.id, update.message.from_user.username, datetime.now(), update.message.from_user.first_name, update.message.from_user.last_name)

                #logger.info(f"User status updated for user {update.message.from_user.id} in chat {update.message.chat.id} ({update.message.chat.title})")


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

                    logger.info("Question detected " + update.message.text)

                    if len(rows) > 0:
                        logger.info("Vectors detected " + str(rows) + str(rows[0]['similarity']))

                        #TODO this is a debug solution to skip questions with high similarity
                        if rows[0]['similarity'] < float(config['OPENAI']['SIMILARITY_THRESHOLD']):
                            logger.info("Skip, similarity=" + str(rows[0]['similarity']) + f" while threshold={config['OPENAI']['SIMILARITY_THRESHOLD']}", critical=False)
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
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")


def db_update_user(user_id, chat_id, username, last_message_datetime, first_name=None, last_name=None):
    #TODO: we need to relocate this function to another location

    with db_helper.session_scope() as db_session:
        if chat_id is None:
            logger.info(f"Debug: no chat_id for user {user_id} ({username}) last_message_datetime")

        # Update or insert user
        user = db_session.query(db_helper.User).filter_by(id=user_id).first()
        if user:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
        else:
            user = db_helper.User(id=user_id, username=username, first_name=first_name, last_name=last_name)
            db_session.add(user)

        # Update or insert user status
        user_status = db_session.query(db_helper.User_Status).filter_by(user_id=user_id, chat_id=chat_id).first()
        if user_status:
            user_status.last_message_datetime = last_message_datetime
        else:
            user_status = db_helper.User_Status(user_id=user_id, chat_id=chat_id, last_message_datetime=last_message_datetime)
            db_session.add(user_status)

        db_session.commit()

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

        # reporting
        application.add_handler(CommandHandler('report', tg_report, filters.ChatType.SUPERGROUP), group=4)

        # Add a handler for chat join requests
        application.add_handler(ChatJoinRequestHandler(tg_join_request), group=5)

        # Start the Bot
        application.run_polling()
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
if __name__ == '__main__':
    main()
