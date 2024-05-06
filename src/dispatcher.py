import os
from telegram import Bot
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ChatJoinRequestHandler
from telegram.request import HTTPXRequest
from telegram.error import TelegramError
from datetime import datetime, timedelta, timezone
import openai
import traceback
import re
import asyncio
import signal
import sys
import json
from re import findall

from langdetect import detect
import langdetect

import src.logging_helper as logging
import src.openai_helper as openai_helper
import src.chat_helper as chat_helper
import src.db_helper as db_helper
import src.config_helper as config_helper
import src.user_helper as user_helper
import src.rating_helper as rating_helper
import src.reporting_helper as reporting_helper
import src.message_helper as message_helper
import src.spamcheck_helper as spamcheck_helper

config = config_helper.get_config()

logger = logging.get_logger()

logger.info(f"Starting {__file__} in {config['BOT']['MODE']} mode at {os.uname()}")

bot = Bot(config['BOT']['KEY'],
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

########################

async def tg_help(update, context):
    try:
        # just return all commands we support as a reply
        chat_id = update.effective_chat.id
        message = update.message

        commands = [
            "/report - report a message, should be used as a reply to a message",
            "/pin - pin a message, should be used as a reply to a message",
            "/unpin - unpin a message, should be used as a reply to a message",
            "/help - show this message"
        ]

        await chat_helper.send_message(bot, chat_id, "Supported commands:\n" + "\n".join(commands), reply_to_message_id=message.message_id, delete_after=5 * 60)
        await chat_helper.schedule_message_deletion(chat_id, message.message_id, message.from_user.id, delay_seconds=5*60)

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_report(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        if not message or not message.reply_to_message:
            logger.info("Report command without a message to reply to.")
            return

        reported_message_id = message.reply_to_message.message_id
        reported_user_id = message.reply_to_message.from_user.id
        reporting_user_id = message.from_user.id

        if message:
            await chat_helper.schedule_message_deletion(chat_id,  message.message_id, message.from_user.id, trigger_id = reported_message_id, delay_seconds = 2*60*60) #use reported_message_id as trigger_id

        chat_administrators = await context.bot.get_chat_administrators(chat_id)
        if any(admin.user.id == reported_user_id for admin in chat_administrators):
            await chat_helper.send_message(context.bot, chat_id, "You cannot report an admin.", delete_after=120)
            return

        reporting_user_rating = rating_helper.get_rating(reporting_user_id, chat_id)
        user_rating_to_power_ratio = int(chat_helper.get_chat_config(chat_id, 'user_rating_to_power_ratio', default=0))
        report_power = 1 if user_rating_to_power_ratio == 0 else max(1, reporting_user_rating // user_rating_to_power_ratio)

        # Check if the reporting user is not an admin (if he is an admin he can report several times)
        if not any(admin.user.id == reporting_user_id for admin in chat_administrators):
            # If the reported user has already been reported by the reporting user, send a message and return
            if await reporting_helper.check_existing_report(chat_id, reported_user_id, reporting_user_id):
                await chat_helper.send_message(context.bot, chat_id, "This user has already been reported by you.", reply_to_message_id=message.message_id, delete_after=120)
                return

        success = await reporting_helper.add_report(reported_user_id, reporting_user_id, reported_message_id, chat_id, report_power)
        if not success:
            logger.error("Failed to add report.")
            return

        report_sum = await reporting_helper.get_total_reports(chat_id, reported_user_id)
        if report_sum is None:
            logger.error("Failed to calculate cumulative report power.")
            return

        number_of_reports_to_warn = int(chat_helper.get_chat_config(chat_id, 'number_of_reports_to_warn'))
        number_of_reports_to_ban = int(chat_helper.get_chat_config(chat_id, 'number_of_reports_to_ban'))

        reported_user_mention = user_helper.get_user_mention(reported_user_id, chat_id)
        chat_mention = await chat_helper.get_chat_mention(context.bot, chat_id)

        await chat_helper.send_message_to_admin(context.bot, chat_id, f"User {reported_user_mention} has been reported by {user_helper.get_user_mention(reporting_user_id, chat_id)} in chat {chat_mention} {report_sum}/{number_of_reports_to_ban} times.\nReported message: {message.reply_to_message.text}")
        logger.info(f"User {reported_user_id} has been reported by {user_helper.get_user_mention(reporting_user_id, chat_id)} in chat {chat_id} {report_sum}/{number_of_reports_to_ban} times. Reported message: {message.reply_to_message.text}")

        if report_sum >= number_of_reports_to_ban:
            # let's now increase rating for all users who reported this user
            reporting_user_ids = await reporting_helper.get_reporting_users(chat_id, reported_user_id)
            bot_info = await bot.get_me()
            await rating_helper.change_rating(reporting_user_ids, bot_info.id, chat_id, 1, delete_message_delay=120)

            await chat_helper.ban_user(context.bot, chat_id, reported_user_id)
            await chat_helper.delete_message(context.bot, chat_id, reported_message_id)
            await chat_helper.send_message(context.bot, chat_id, f"User {reported_user_mention} has been banned due to {report_sum}/{number_of_reports_to_ban} reports.", delete_after=120)
            await chat_helper.send_message_to_admin(context.bot, chat_id, f"User {reported_user_mention} has been banned in chat {chat_mention} due to {report_sum}/{number_of_reports_to_ban} reports. \nReported message: {message.reply_to_message.text}")

            # now delete all messages from scheduled deletion with trigger_id = reported_message_id
            await chat_helper.delete_scheduled_messages(bot, chat_id, trigger_id = reported_message_id)

            # Log the ban action
            await  message_helper.log_or_update_message(
                reported_user_id,
                reported_user_mention,
                rating_helper.get_rating(reported_user_id, chat_id),
                chat_id,
                message.reply_to_message.text,
                "report & ban",
                reporting_user_id,
                user_helper.get_user_mention(reporting_user_id, chat_id),
                f"User {reported_user_mention} was banned in chat {chat_mention} due to {report_sum}/{number_of_reports_to_ban} reports.",
                reported_message_id,
                is_spam=True)

        elif report_sum >= number_of_reports_to_warn:
            await chat_helper.warn_user(context.bot, chat_id, reported_user_id)
            await chat_helper.mute_user(context.bot, chat_id, reported_user_id)
            await chat_helper.send_message(context.bot, chat_id, f"User {reported_user_mention} has been warned and muted due to {report_sum}/{number_of_reports_to_ban} reports.", reply_to_message_id=reported_message_id, delete_after=120)
            await chat_helper.send_message_to_admin(context.bot, chat_id, f"User {reported_user_mention} has been warned and muted in chat {chat_mention} due to {report_sum}/{number_of_reports_to_ban} reports. \nReported message: {message.reply_to_message.text}")
        else:
            user_has_been_reported_message = await chat_helper.send_message(context.bot, chat_id, f"User {reported_user_mention} has been reported {report_sum}/{number_of_reports_to_ban} times.")
            await chat_helper.schedule_message_deletion(chat_id, message_id = user_has_been_reported_message.message_id, user_id=reported_user_id, trigger_id=reported_message_id)



    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_set_report(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        # Verify if the command issuer is an administrator
        chat_administrators = await context.bot.get_chat_administrators(chat_id)
        is_admin = any(admin.user.id == message.from_user.id for admin in chat_administrators)
        if not is_admin:
            await chat_helper.send_message(context.bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after=120)
            return

        reported_user_id = None
        command_parts = message.text.split()
        # Verify that the command is correctly formatted with at least two arguments
        if len(command_parts) < 3:
            await chat_helper.send_message(context.bot, chat_id, "Usage: /set_report [@username or user_id] [report_count]", reply_to_message_id=message.message_id)
            return

        new_report_count = int(command_parts[2])  # This is the desired report count

        # Determine the target user ID based on the input method
        if message.reply_to_message:
            reported_user_id = message.reply_to_message.from_user.id
        elif command_parts[1].isdigit():  # Direct user ID input
            reported_user_id = int(command_parts[1])
        elif '@' in command_parts[1]:  # Username input
            reported_user_id = user_helper.get_user_id(username=command_parts[1][1:])
            if reported_user_id is None:
                await chat_helper.send_message(context.bot, chat_id, f"No user found with username {command_parts[1]}.", reply_to_message_id=message.message_id)
                return
        else:
            await chat_helper.send_message(context.bot, chat_id, "Invalid format. Use /set_report @username or /set_report user_id report_count.", reply_to_message_id=message.message_id)
            return

        # Get the current total reports to calculate the needed adjustment
        current_reports = await reporting_helper.get_total_reports(chat_id, reported_user_id)
        adjustment = new_report_count - current_reports

        # Apply the adjustment to set the new report count
        if adjustment != 0:
            await reporting_helper.add_report(reported_user_id, message.from_user.id, "Adjusting with /set_report command", chat_id, adjustment)

        await chat_helper.send_message(context.bot, chat_id, f"Report count for user ID: {reported_user_id} set to {new_report_count}.")
    except ValueError:
        await chat_helper.send_message(context.bot, chat_id, "Invalid number for report count. Please specify an integer.", reply_to_message_id=message.message_id)
    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")


async def tg_pin(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message
        user_mention = user_helper.get_user_mention(message.from_user.id, chat_id)

        if not message.reply_to_message:
            await chat_helper.send_message(bot, chat_id, "Reply to a message to pin it.", reply_to_message_id=message.message_id, delete_after = 120)
            return

        await chat_helper.pin_message(bot, chat_id, message.reply_to_message.message_id)
        await chat_helper.send_message(bot, chat_id, f"Message pinned by {user_mention}.", delete_after = 120, reply_to_message_id=message.reply_to_message.message_id)
        logger.info(f"Message pinned by {user_mention} in chat {chat_id}.")



    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_unpin(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message
        user_mention = user_helper.get_user_mention(message.from_user.id, chat_id)

        await chat_helper.unpin_message(bot, chat_id, message.reply_to_message.message_id)
        await chat_helper.send_message(bot, chat_id, f"Message unpinned by {user_mention}.", delete_after = 120, reply_to_message_id=message.reply_to_message.message_id)
        logger.info(f"Message unpinned by {user_mention} in chat {chat_id}.")

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_warn(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message
        admin_ids = [admin.user.id for admin in await bot.get_chat_administrators(chat_id)]

        await chat_helper.delete_message(bot, chat_id, message.message_id, delay_seconds=120)  # clean up the command message

        # TODO:MED: We should find the way how to identify admin if he answes from channel
        if message.from_user.id not in admin_ids:
            await chat_helper.send_message(bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after = 120)
            return

        if not message.reply_to_message:
            await chat_helper.send_message(bot, chat_id, "Reply to a message to warn the user.", reply_to_message_id=message.message_id, delete_after = 120)
            return

        reason = ' '.join(message.text.split()[1:]) or "You've been warned by an admin."
        warned_user_id = message.reply_to_message.from_user.id
        warned_message_id = message.reply_to_message.message_id

        with db_helper.session_scope() as db_session:
            report = db_helper.Report(
                reported_user_id=warned_user_id,
                reporting_user_id=message.from_user.id,
                reported_message_id=warned_message_id,
                chat_id=chat_id,
                reason=reason
            )
            db_session.add(report)
            db_session.commit()

            warn_count = db_session.query(db_helper.Report).filter(
                db_helper.Report.chat_id == chat_id,
                db_helper.Report.reported_user_id == warned_user_id,
                db_helper.Report.reason != None
            ).count()

            number_of_reports_to_ban = int(chat_helper.get_chat_config(chat_id, 'number_of_reports_to_ban'))

            warned_user_mention = user_helper.get_user_mention(warned_user_id, chat_id)
            warning_admin_mention = user_helper.get_user_mention(message.from_user.id, chat_id)

            if warn_count >= number_of_reports_to_ban:
                await chat_helper.delete_message(bot, chat_id, warned_message_id)
                await chat_helper.ban_user(bot, chat_id, warned_user_id)
                warned_user_mention = user_helper.get_user_mention(warned_user_id, chat_id)
                await chat_helper.send_message(bot, chat_id, f"User {warned_user_mention} has been banned due to {warn_count} warnings.", delete_after=120)
                await chat_helper.send_message_to_admin(bot, chat_id, f"User {warned_user_mention} has been banned in chat {await chat_helper.get_chat_mention(bot, chat_id)} due to {warn_count}/{number_of_reports_to_ban} warnings.")

                reporting_user_ids = db_session.query(db_helper.Report.reporting_user_id).filter(
                    db_helper.Report.reported_user_id == warned_user_id,
                    db_helper.Report.chat_id == chat_id
                ).distinct().all()
                reporting_user_ids = [item[0] for item in reporting_user_ids]

                bot_info = await bot.get_me()
                for user_id in reporting_user_ids:
                    await rating_helper.change_rating(user_id, bot_info.id, chat_id, 1, delete_message_delay = 120)

                return

            await chat_helper.send_message(bot, chat_id, f"{warned_user_mention}, you've been warned {warn_count}/{number_of_reports_to_ban} times. Reason: {reason}", reply_to_message_id=warned_message_id)
            await chat_helper.delete_message(bot, chat_id, warned_message_id)
            await chat_helper.send_message_to_admin(bot, chat_id, f"{warning_admin_mention} warned {warned_user_mention} in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {reason}. Total Warnings: {warn_count}/{number_of_reports_to_ban}")

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")


async def tg_ban(update, context):
    try:
        with db_helper.session_scope() as db_session:
            message = update.message
            chat_id = update.effective_chat.id
            ban_user_id = None

            await chat_helper.delete_message(bot, chat_id, message.message_id)  # clean up the command message

            # Check if the command was sent by an admin of the chat
            chat_administrators = await bot.get_chat_administrators(chat_id)

            # TODO:MED: We should find the way how to identify admin if he answes from channel
            if message.from_user.id not in [admin.user.id for admin in chat_administrators]:
                await chat_helper.send_message(bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after = 120)
                return

            command_parts = message.text.split()  # Split the message into parts
            if len(command_parts) > 1:  # if the command has more than one part (means it has a user ID or username parameter)
                if '@' in command_parts[1]:  # if the second part is a username
                    user = db_session.query(db_helper.User).filter(db_helper.User.username == command_parts[1][1:]).first()  # Remove @ and query
                    if user is None:
                        await message.reply_text(f"No user found with username {command_parts[1]}.")
                        return
                    ban_user_id = user.id
                elif command_parts[1].isdigit():  # if the second part is a user ID
                    ban_user_id = int(command_parts[1])
                else:
                    await message.reply_text("Invalid format. Use /ban @username or /ban user_id.")
                    return
            else: # Check if a user is mentioned in the command message as a reply to message
                if not message.reply_to_message:
                    await message.reply_text("Please reply to a user's message to ban them.")
                    return
                ban_user_id = message.reply_to_message.from_user.id

                await chat_helper.delete_message(bot, chat_id, message.reply_to_message.message_id)

            # Check if the user to ban is an admin of the chat
            for admin in chat_administrators:
                if admin.user.id == ban_user_id:
                    await message.reply_text("You cannot ban an admin.")
                    return

            # Ban the user
            await chat_helper.ban_user(bot, chat_id, ban_user_id)

            # Log the ban action
            await message_helper.log_or_update_message(
                user_id=ban_user_id,
                user_nickname=user_helper.get_user_mention(ban_user_id, chat_id),
                user_current_rating=rating_helper.get_rating(ban_user_id, chat_id),
                chat_id=chat_id,
                message_content=message.reply_to_message.text,
                action_type="ban",
                reporting_id=message.from_user.id,
                reporting_id_nickname=user_helper.get_user_mention(message.from_user.id, chat_id),
                reason_for_action=f"User {user_helper.get_user_mention(ban_user_id, chat_id)} was banned in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {message.text}",
                message_id=message.reply_to_message.message_id,
                is_spam=True
            )


            await chat_helper.send_message(bot, chat_id, f"User {user_helper.get_user_mention(ban_user_id, chat_id)} has been banned.", delete_after=120)

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_gban(update, context):
    try:
        with db_helper.session_scope() as db_session:
            message = update.message
            chat_id = update.effective_chat.id
            ban_user_id = None
            ban_chat_id = None
            ban_reason = None

            # Check if the command was sent by a global admin of the bot
            # TODO:MED: We should find the way how to identify admin if he answes from channel
            if message.from_user.id != int(config['BOT']['ADMIN_ID']):
                #print chat_id
                await message.reply_text("You must be a global bot admin to use this command.")
                return

            await bot.delete_message(chat_id, message.message_id)  # delete the ban command message

            command_parts = message.text.split()  # Split the message into parts
            if len(command_parts) > 1:  # if the command has more than one part (means it has a user ID or username parameter)
                ban_reason = f"User was globally banned by {message.text} command."
                if '@' in command_parts[1]:  # if the second part is a username
                    user = db_session.query(db_helper.User).filter(db_helper.User.username == command_parts[1][1:]).first()  # Remove @ and query
                    if user is None:
                        await message.reply_text(f"No user found with username {command_parts[1]}.")
                        return
                    ban_user_id = user.id
                elif command_parts[1].isdigit():  # if the second part is a user ID
                    ban_user_id = int(command_parts[1])
                else:
                    await message.reply_text("Invalid format. Use gban @username or gban user_id.")
                    return
            elif chat_id == int(config['LOGGING']['INFO_CHAT_ID']) or chat_id == int(
                    config['LOGGING']['ERROR_CHAT_ID']):
                ban_reason = f"User was globally banned by {message.text} command in info chat. Message: {message.reply_to_message.text}"
                if not message.reply_to_message:
                    await message.reply_text("Please reply to a message containing usernames to ban.")
                    return
                username_list = re.findall('@(\w+)',
                                           message.reply_to_message.text)  # extract usernames from the reply_to_message
                if len(username_list) > 2:  # Check if there are more than 2 usernames in the message
                    await message.reply_text("More than two usernames found. Please specify which user to ban.")
                    return
                elif len(username_list) == 0:  # Check if there are no usernames in the message
                    await message.reply_text("No usernames found. Please specify which user to ban.")
                    return
                else:  # There is exactly one username
                    # Fetch user_id based on username from database
                    user = db_session.query(db_helper.User).filter(db_helper.User.username == username_list[0]).first()
                    if user is None:
                        await message.reply_text(f"No user found with username {username_list[0]}.")
                        return
                    ban_user_id = user.id
            else: # Check if a user is mentioned in the command message as a reply to message
                ban_reason = f"User was globally banned by {message.text} command in {await chat_helper.get_chat_mention(bot, chat_id)}. Message: {message.reply_to_message.text}"
                ban_chat_id = chat_id # We need to ban in the same chat as the command was sent

                if not message.reply_to_message:
                    await message.reply_text("Please reply to a user's message to ban them.")
                    return
                ban_user_id = message.reply_to_message.from_user.id

                await chat_helper.delete_message(bot, chat_id, message.reply_to_message.message_id)

            # Ban the user and add them to the banned_users table
            await chat_helper.ban_user(bot, ban_chat_id, ban_user_id, True, reason=ban_reason)

            # Log the ban action
            await message_helper.log_or_update_message(
                user_id=ban_user_id,
                user_nickname=user_helper.get_user_mention(ban_user_id, chat_id),
                user_current_rating=rating_helper.get_rating(ban_user_id, chat_id),
                chat_id=chat_id,
                message_content=message.reply_to_message.text,
                action_type="ban",
                reporting_id=message.from_user.id,
                reporting_id_nickname=user_helper.get_user_mention(message.from_user.id, chat_id),
                reason_for_action=f"User {user_helper.get_user_mention(ban_user_id, chat_id)} was banned in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {message.text}",
                message_id=message.reply_to_message.message_id,
                is_spam=True
            )

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")


#TODO: MEDIUM: May be we need to make it more complicated (e.g. with ai embeddings) and move big part of it to separate auto_deply_helper
async def tg_auto_reply(update, context):
    try:
        if update.message and update.message.text:  # Check if the message and its text exist
            chat_id = update.effective_chat.id
            message_text = update.message.text.lower()  # Continue with the rest of your function...
        else:
            return  # Skip processing if there's no text message

        # Fetch auto replies that are not currently delayed
        auto_replies = await chat_helper.get_auto_replies(chat_id, filter_delayed=True)

        # Extract whole words from the message using regular expression.
        message_words = set(findall(r'\b\w+\b', message_text))

        for auto_reply in auto_replies:
            # Decode the JSON-encoded list of triggers
            triggers = json.loads(auto_reply['trigger'].lower())

            # Check if any of the triggers is a whole word in the message text
            if any(findall(r'\b' + re.escape(trigger) + r'\b', message_text) for trigger in triggers):
                # Send the auto-reply message and update the last reply time
                await chat_helper.send_message(context.bot, chat_id, auto_reply['reply'], reply_to_message_id=update.message.message_id)
                await chat_helper.update_last_reply_time_and_increment_count(chat_id, auto_reply['id'], datetime.now(timezone.utc))
                logger.info(f"Auto-reply sent in chat {chat_id} for triggers '{', '.join(triggers)}': {auto_reply['reply']}")  # If you still want multiple replies remove the break  # break

    except Exception as error:
        logger.error(f"tg_auto_reply error: {traceback.format_exc()}")

async def tg_log_message(update, context):
    try:
        message = update.message
        if message:  # Check if there is an actual message to log
            user_id = message.from_user.id
            user_nickname = message.from_user.username or message.from_user.first_name  # Use username if available, otherwise first name
            chat_id = message.chat.id
            message_content = message.text or "Non-text message"  # Handle non-text messages
            message_id = message.message_id
            user_current_rating = rating_helper.get_rating(user_id, chat_id)  # This needs to be defined in your helpers

            # Assuming you have defined these or have default values to use
            action_type = "message"  # Default action type for logging messages
            reporting_id = user_id  # Since the user is self-reporting by sending a message
            reporting_id_nickname = user_nickname
            reason_for_action = "Regular message"  # Default reason

            embedding = openai_helper.generate_embedding(message_content)

            # Call the log_or_update_message function from your reporting helper
            success = await message_helper.log_or_update_message(
                user_id=user_id,
                user_nickname=user_nickname,
                user_current_rating=user_current_rating,
                chat_id=chat_id,
                message_content=message_content,
                action_type=action_type,
                reporting_id=reporting_id,
                reporting_id_nickname=reporting_id_nickname,
                reason_for_action=reason_for_action,
                message_id=message_id,
                is_spam=False,  # Default to not spam when first logging
                embedding=embedding
            )

            if not success:
                update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
                logger.error(f"Failed to log the message in the database: {traceback.format_exc()} | Update: {update_str}")

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_ai_spam_check(update, context):
    try:
        message = update.message if update.message else update.edited_message
        if not message:
            update_dict = update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}
            update_str = json.dumps(update_dict, indent=4, sort_keys=True, default=str)
            logger.info(f"Update does not contain a message: {update_str}")
            return

        check_spam = chat_helper.get_chat_config(message.chat_id, 'ai_spam_check_enabled')

        if check_spam and message.text:
            text = message.text.strip()
            if text:
                # Call the completion_create function with the prepared prompt
                prompt = [
                    {"role": "user", "content": f"{config['ANTISPAM']['PROMPT']} '{text}'"}
                ]

                response = await openai_helper.chat_completion_create(prompt)

                #let's log prompt for debugging
                #logger.info(f"Prompt: {prompt}")

                # Assuming the response needs to be parsed to extract the spam rating
                try:
                    spam_rating = int(response.choices[0].message.content.strip())
                except ValueError:
                    logger.info(f"Failed to parse spam rating from OpenAI response. Chat name {message.chat.title} | Chat ID: {message.chat_id} | Message from: {message.from_user.username} | Message ID: {message.message_id} | Message text: {message.text} | Spam rating: {response.choices[0].message.content.strip()}")
                    spam_rating = 1
                except AttributeError:
                    logger.error(f"Failed to parse spam rating from OpenAI response. Chat name {message.chat.title} | Chat ID: {message.chat_id} | Message from: {message.from_user.username} | Message ID: {message.message_id} | Message text: {message.text} | Spam rating: {spam_rating}")
                    return

                logger.info(f"ANTISPAM. Chat name {message.chat.title} | Chat ID: {message.chat_id} | Message from: {message.from_user.username} | Message ID: {message.message_id} | Message text: {message.text} | Spam rating: {spam_rating}")

                if spam_rating >= 8:  # Assuming a rating of 10 or more is considered spam
                    await chat_helper.send_message(context.bot, message.chat_id, "It appears to be spam. If that is the case, please respond to the original message with the command /report ", reply_to_message_id=message.message_id, delete_after = 300)
                    logger.info(f"❗ANTISPAM. Chat name {message.chat.title} | Chat ID: {message.chat_id} | Message from: {message.from_user.username} | Message ID: {message.message_id} | Detected spam.")

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")


async def tg_spam_check(update, context):
    try:
        message = update.message if update.message else update.edited_message

        #check if user is admin so don't check spam for them
        chat_administrators = await context.bot.get_chat_administrators(message.chat.id)
        is_admin = any(admin.user.id == message.from_user.id for admin in chat_administrators)
        if is_admin:
            return

        if message:
            agressive_antispam = chat_helper.get_chat_config(message.chat.id, "agressive_antispam")
        else:
            # Convert the update object to a dictionary
            update_dict = update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}
            # Serialize the dictionary to a JSON-formatted string
            update_str = json.dumps(update_dict, indent=4, sort_keys=True, default=str)
            # Log the serialized update
            logger.warning(f"Update does not contain a message: {update_str}")
            return

        if agressive_antispam == True:
            # TODO:HIGH: This is a very temporary antispam check. We need to implement a better solution (e.g. with a machine learning model or OpenAI's GPT-4)
            if update.message and update.message.text:
                text = update.message.text.strip()
                if text:
                    try:
                        lang = detect(text)
                        if lang in ['ar', 'fa', 'ur', 'he', 'ps', 'sd', 'ku', 'ug', 'fa', 'zh']:
                            # Ban the user for using a filtered language
                            await chat_helper.delete_message(bot, message.chat.id, message.message_id)
                            await chat_helper.ban_user(bot, message.chat.id, message.from_user.id, reason=f"Filtered language used. Message {message.text}. Chat: {await chat_helper.get_chat_mention(bot, message.chat.id)}", global_ban=True)
                            await chat_helper.send_message(bot, message.chat.id, f"User {user_helper.get_user_mention(message.from_user.id, message.chat.id)} has been banned based on language filter. - {lang}", delete_after=120)
                            return  # exit the function as the user has already been banned
                    except langdetect.lang_detect_exception.LangDetectException as e:
                        if "No features in text." in str(e):
                            # No features in text
                            pass

            # Check for APK files
            if message and message.document:
                if message.document.file_name and message.document.file_name.endswith('.apk'):
                    # Ban the user for sending an APK file
                    await chat_helper.delete_message(bot, message.chat.id, message.message_id)
                    await chat_helper.ban_user(bot, message.chat.id, message.from_user.id, reason=f"APK file uploaded. Chat: {await chat_helper.get_chat_mention(bot, message.chat.id)}", global_ban=True)
                    await chat_helper.send_message(bot, message.chat.id, f"User {user_helper.get_user_mention(message.from_user.id, message.chat.id)} has been banned for uploading an APK file.", delete_after=120)
                    return  # exit the function as the user has already been banned

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")


async def tg_new_spamcheck(update, context):
    #TODO:HIGH: We currently calculate embeddings twice. Once in tg_log_message and once during prediction. We should reorganize this to avoid redundant calculations.
    message = update.message

    if not message or not message.from_user:
        return

    if chat_helper.get_chat_config(message.chat.id, "new_spamcheck_enabled") != True:
        return

    if any(admin.user.id == message.from_user.id for admin in await context.bot.get_chat_administrators(message.chat.id)):
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    message_text = message.text

    try:
        spam_proba = await spamcheck_helper.predict_spam(user_id, chat_id, message_text=message_text)
        delete_threshold = float(config['ANTISPAM']['DELETE_THRESHOLD'])
        mute_threshold = float(config['ANTISPAM']['MUTE_THRESHOLD'])

        if spam_proba < delete_threshold:
            logger.info(f"Not Spam. Probability: {spam_proba:.5f}. Threshold: {delete_threshold}. Message: {message_text}. Chat: {await chat_helper.get_chat_mention(bot, chat_id)}. User: {user_helper.get_user_mention(user_id, chat_id)}")
            return

        if spam_proba >= mute_threshold:
            logger.info(f"‼️Spam (delete, mute) ‼️ Probability: {spam_proba:.5f}. Threshold: {mute_threshold}. Message: {message_text}. Chat: {await chat_helper.get_chat_mention(bot, chat_id)}. User: {user_helper.get_user_mention(user_id, chat_id)}")
            await chat_helper.mute_user(bot, chat_id, user_id, 7 * 24)
        else:
            logger.info(f"‼️Spam (delete) ‼️ Probability: {spam_proba:.5f}. Threshold: {delete_threshold}. Message: {message_text}. Chat: {await chat_helper.get_chat_mention(bot, chat_id)}. User: {user_helper.get_user_mention(user_id, chat_id)}")

        await chat_helper.delete_message(bot, chat_id, message.message_id)
        await message_helper.log_or_update_message(
            user_id=user_id,
            user_nickname=message.from_user.first_name,
            user_current_rating=rating_helper.get_rating(user_id, chat_id),
            chat_id=chat_id,
            message_content=message_text,
            action_type="spam detection",
            reporting_id=context.bot.id,
            reporting_id_nickname="rv_tg_community_bot",
            reason_for_action="Automated spam detection",
            message_id=message.message_id,
            is_spam=True
        )

    except Exception as error:
        logger.error(f"Error processing spam check for User ID: {user_id}, Chat ID: {chat_id}, Error: {error}, Message: {message_text}")


async def tg_thankyou(update, context):
    try:
        with db_helper.session_scope() as db_session:

            if update.message is not None \
                    and update.message.reply_to_message is not None \
                    and update.message.reply_to_message.from_user.id != update.message.from_user.id:

                # there is a strange behaviour when user send message in topic Telegram show it as a reply to forum_topic_created invisible message. We don't need to process it
                if update.message.reply_to_message.forum_topic_created is not None:
                    return

                like_words = chat_helper.get_chat_config(update.message.chat.id, "like_words")
                dislike_words = chat_helper.get_chat_config(update.message.chat.id, "dislike_words")

                for category, word_list in {'like_words': like_words, 'dislike_words': dislike_words}.items():
                    if word_list is not None:
                        for word in word_list:
                             #check without case if word in update message
                            if word.lower() in update.message.text.lower():

                                user = db_session.query(db_helper.User).filter(
                                    db_helper.User.id == update.message.reply_to_message.from_user.id).first()
                                if user is None:
                                    user = db_helper.User(id=update.message.reply_to_message.from_user.id,
                                                          first_name=update.message.reply_to_message.from_user.first_name,
                                                          last_name=update.message.reply_to_message.from_user.last_name,
                                                          username=update.message.reply_to_message.from_user.username)
                                    db_session.add(user)
                                    db_session.commit()

                                judge = db_session.query(db_helper.User).filter(
                                    db_helper.User.id == update.message.from_user.id).first()
                                if judge is None:
                                    judge = db_helper.User(id=update.message.from_user.id,
                                                           name=update.message.from_user.first_name)
                                    db_session.add(judge)
                                    db_session.commit()

                                if category == "like_words":
                                    await rating_helper.change_rating(update.message.reply_to_message.from_user.id, update.message.from_user.id, update.message.chat.id, 1, update.message.message_id, delete_message_delay=5*60)
                                elif category == "dislike_words":
                                    await rating_helper.change_rating(update.message.reply_to_message.from_user.id, update.message.from_user.id, update.message.chat.id, -1, update.message.message_id, delete_message_delay=5*60)

                                db_session.close()

                                return
            else:
                pass
    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_set_rating(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        # Check if the user is an administrator
        chat_administrators = await context.bot.get_chat_administrators(chat_id)
        is_admin = any(admin.user.id == message.from_user.id for admin in chat_administrators)
        if not is_admin:
            await chat_helper.send_message(context.bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after=120)
            return

        target_user_id = None
        new_rating = None

        # Handle reply to a message or direct command input
        if message.reply_to_message:
            target_user_id = message.reply_to_message.from_user.id
            if len(message.text.split()) < 2:
                await chat_helper.send_message(context.bot, chat_id, "Please specify a rating.", reply_to_message_id=message.message_id)
                return
            new_rating = int(message.text.split()[1])
        else:
            command_parts = message.text.split()
            if len(command_parts) < 3:
                await chat_helper.send_message(context.bot, chat_id, "Usage: /set_rating [@username or user_id] [rating]", reply_to_message_id=message.message_id)
                return

            user_identifier = command_parts[1]
            new_rating = int(command_parts[2])
            if user_identifier.isdigit():
                target_user_id = int(user_identifier)
            elif user_identifier.startswith('@'):
                target_user_id = user_helper.get_user_id(username=user_identifier[1:])
                if target_user_id is None:
                    await chat_helper.send_message(context.bot, chat_id, f"No user found with username {user_identifier}.", reply_to_message_id=message.message_id)
                    return
            else:
                await chat_helper.send_message(context.bot, chat_id, "Invalid format. Use /set_rating @username or /set_rating user_id rating.", reply_to_message_id=message.message_id)
                return

        # Apply the new rating
        current_rating = rating_helper.get_rating(target_user_id, chat_id)
        adjustment = new_rating - current_rating
        if adjustment != 0:
            await rating_helper.change_rating(target_user_id, message.from_user.id, chat_id, adjustment, message.message_id, delete_message_delay=120)
        else:
            # Specifically handle the case where no change is needed, especially when setting to zero
            await chat_helper.send_message(context.bot, chat_id, f"Rating for user ID {target_user_id} is already set to {new_rating}.")

    except ValueError:
        await chat_helper.send_message(context.bot, chat_id, "Invalid number for rating. Please specify an integer.", reply_to_message_id=message.message_id)
    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

async def tg_get_rating(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        # Check if the command is used as a reply or if parameters are provided
        if not message.reply_to_message and len(message.text.split()) == 1:
            instruction = "Use /get_rating as a reply or specify a user with /get_rating @username or /get_rating user_id."
            await chat_helper.send_message(context.bot, chat_id, instruction, reply_to_message_id=message.message_id, delete_after=120)
            return

        target_user_id = None
        if message.reply_to_message:
            target_user_id = message.reply_to_message.from_user.id
        else:
            user_identifier = message.text.split()[1]
            if user_identifier.isdigit():
                target_user_id = int(user_identifier)
            elif user_identifier.startswith('@'):
                target_user_id = user_helper.get_user_id(username=user_identifier[1:])
                if target_user_id is None:
                    await chat_helper.send_message(context.bot, chat_id, f"No user found with username {user_identifier}.", reply_to_message_id=message.message_id)
                    return
            else:
                await chat_helper.send_message(context.bot, chat_id, "Invalid format. Use /get_rating @username or /get_rating user_id.", reply_to_message_id=message.message_id)
                return

        current_rating = rating_helper.get_rating(target_user_id, chat_id)

        user_mention = user_helper.get_user_mention(target_user_id, chat_id)
        await chat_helper.send_message(context.bot, chat_id, f"Rating for user {user_mention} is {current_rating}.", reply_to_message_id=message.message_id)

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")




async def tg_join_request(update, context):
    try:
        welcome_dm_message = chat_helper.get_chat_config(update.effective_chat.id, "welcome_dm_message")
        auto_approve_join_request = chat_helper.get_chat_config(update.effective_chat.id, "auto_approve_join_request")

        if welcome_dm_message is not None and welcome_dm_message != "":
            try:
                await chat_helper.send_message(bot, update.effective_user.id, welcome_dm_message, disable_web_page_preview=True)
                logger.info(f"Welcome message sent to user {update.effective_user.id} in chat {update.effective_chat.id} ({update.effective_chat.title})")
            except TelegramError as e:
                if "bot can't initiate conversation with a user" in e.message:
                    logger.info(f"Bot can't initiate conversation with user {update.effective_user.id} in chat {update.effective_chat.id} ({update.effective_chat.title})")
                else:
                    logger.error(f"Telegram error: {e.message}. Traceback: {traceback.format_exc()}")
            except Exception as e:
                logger.error(f"General error: {traceback.format_exc()}")

    except TelegramError as e:
        logger.error(f"Telegram error: {e.message}. Traceback: {traceback.format_exc()}")

    except Exception as e:
        logger.error(f"General error: {traceback.format_exc()}")

    finally:
        if auto_approve_join_request:
            try:
                await update.chat_join_request.approve()
            except Exception as e:
                logger.error(f"Error while trying to approve chat join request: {traceback.format_exc()}")



async def tg_new_member(update, context):
    try:
        new_user_id = update.message.api_kwargs['new_chat_participant']['id']

        delete_new_chat_members_message = chat_helper.get_chat_config(update.effective_chat.id, "delete_new_chat_members_message")

        if delete_new_chat_members_message == True:
            await bot.delete_message(update.message.chat.id,update.message.id)

            logger.info(f"Joining message deleted from chat {await chat_helper.get_chat_mention(bot, update.message.chat.id)} for user @{update.message.from_user.username} ({update.message.from_user.id})")

        with db_helper.session_scope() as db_session:
            #check user in global ban list User_Global_Ban
            user_global_ban = db_session.query(db_helper.User_Global_Ban).filter(db_helper.User_Global_Ban.user_id == new_user_id).first()
            if user_global_ban is not None:
                logger.info(f"User {new_user_id} is in global ban list. Kicking from chat {update.message.chat.title} ({update.message.chat.id})")
                await chat_helper.ban_user(bot, update.message.chat.id, new_user_id, reason="User is in global ban list")
                await chat_helper.send_message(bot, update.message.chat.id, f"User {new_user_id} is in global ban list. Kicking from chat {update.message.chat.title} ({update.message.chat.id})", delete_after=120)
                return

        welcome_message = chat_helper.get_chat_config(update.effective_chat.id, "welcome_message")

        if welcome_message is not None and welcome_message != "":
            #TODO:MED: Add user mention (with smart approachthrough function get_user_mention. But we need to put it inside message, so use template vars)
            await chat_helper.send_message(bot, update.effective_chat.id, welcome_message, disable_web_page_preview=True)

    except Exception as e:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

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
                    user_helper.db_upsert_user(update.message.new_chat_members[0].id, update.message.chat.id,  update.message.new_chat_members[0].username, datetime.now(), update.message.new_chat_members[0].first_name, update.message.new_chat_members[0].last_name)
                else:
                    # TODO:HIGH: We need to rewrite this so we can also add full name
                    user_helper.db_upsert_user(update.message.from_user.id, update.message.chat.id, update.message.from_user.username, datetime.now(), update.message.from_user.first_name, update.message.from_user.last_name)

                #logger.info(f"User status updated for user {update.message.from_user.id} in chat {update.message.chat.id} ({update.message.chat.title})")

            delete_channel_bot_message = chat_helper.get_chat_config(update.message.chat.id, "delete_channel_bot_message") #delete messages that posted by channels, not users

            if delete_channel_bot_message == True:
                if update.message.from_user.is_bot == True and update.message.from_user.name == "@Channel_Bot":
                    #get all admins for this chat

                    delete_channel_bot_message_allowed_ids = chat_helper.get_chat_config(update.message.chat.id, "delete_channel_bot_message_allowed_ids")

                    if delete_channel_bot_message_allowed_ids is None or update.message.sender_chat.id not in delete_channel_bot_message_allowed_ids:
                        await bot.delete_message(update.message.chat.id, update.message.id)
                        await chat_helper.send_message(bot, update.message.chat.id, update.message.text)
                        logger.info(
                            f"Channel message deleted from chat {update.message.chat.title} ({update.message.chat.id}) for user @{update.message.from_user.username} ({update.message.from_user.id})")

            # #TODO: we need to separate this part of the code to separate funciton tg_openai_autorespond
            # if update.message.chat.id == -1001588101140: #O1
            # # if update.message.chat.id == -1001688952630:  # debug
            #     #TODO: we need to support multiple chats, settings in db etc
            #
            #     #Let's here check if we know an answer for a question and send it to user
            #     openai.api_key = config['OPENAI']['KEY']
            #
            #     messages = [
            #         {"role": "system",
            #          "content": f"Answer only yes or no"},
            #             {"role": "user", "content": f"Is this a question: \"{update.message.text}\""}
            #     ]
            #
            #     response = openai.ChatCompletion.create(
            #         model=config['OPENAI']['COMPLETION_MODEL'],
            #         messages=messages,
            #         temperature=float(config['OPENAI']['TEMPERATURE']),
            #         max_tokens=int(config['OPENAI']['MAX_TOKENS']),
            #         top_p=1,
            #         frequency_penalty=0,
            #         presence_penalty=0
            #     )
            #
            #     #check if response.choices[0].message.content contains "yes" without case sensitivity
            #     if "yes" in response.choices[0].message.content.lower():
            #         rows = openai_helper.get_nearest_vectors(update.message.text, 0)
            #
            #         logger.info("Question detected " + update.message.text)
            #
            #         if len(rows) > 0:
            #             logger.info("Vectors detected " + str(rows) + str(rows[0]['similarity']))
            #
            #             #TODO this is a debug solution to skip questions with high similarity
            #             if rows[0]['similarity'] < float(config['OPENAI']['SIMILARITY_THRESHOLD']):
            #                 logger.info("Skip, similarity=" + str(rows[0]['similarity']) + f" while threshold={config['OPENAI']['SIMILARITY_THRESHOLD']}")
            #                 return #skip this message
            #
            #             messages = [
            #                 {"role": "system",
            #                  "content": f"Answer in one Russian message based on user question and embedding vectors. Do not mention embedding. Be applicable and short."},
            #                 {"role": "user", "content": f"\"{update.message.text}\""}
            #             ]
            #
            #             for i in range(len(rows)):
            #                 messages.append({"role": "system", "content": f"Embedding Title {i}: {rows[i]['title']}\n Embedding Body {i}: {rows[i]['body']}"})
            #
            #             response = openai.ChatCompletion.create(
            #                 model=config['OPENAI']['COMPLETION_MODEL'],
            #                 messages=messages,
            #                 temperature=float(config['OPENAI']['TEMPERATURE']),
            #                 max_tokens=int(config['OPENAI']['MAX_TOKENS']),
            #                 top_p=1,
            #                 frequency_penalty=0,
            #                 presence_penalty=0
            #             )
            #             await chat_helper.send_message(bot, update.message.chat.id, response.choices[0].message.content + f" ({rows[0]['similarity']:.2f})", reply_to_message_id=update.message.message_id)
            #
            #             #resend update.message to admin
            #             await bot.forward_message(config['BOT']['ADMIN_ID'], update.message.chat.id, update.message.message_id)
            #             await chat_helper.send_message(bot, config['BOT']['ADMIN_ID'], response.choices[0].message.content + f" ({rows[0]['similarity']:.2f})", disable_web_page_preview=True)
    except Exception as e:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

class BotManager:
    def __init__(self):
        self.application = None

    def signal_handler(self, signum, frame):
        logger.error(f"Signal {signum} received, exiting...") #TODO:MED: log as an error for now, we will change it to info later

        # If your library supports stopping the polling:
        if self.application:
            self.application.stop()

        sys.exit(0)

    def run(self):
        try:
            self.application = Application.builder().token(config['BOT']['KEY']).build()

            # log all messages
            self.application.add_handler(MessageHandler(filters.TEXT, tg_log_message), group=0)


            # delete new member message
            self.application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_new_member), group=1)

            # wiretapping
            self.application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.SUPERGROUP, tg_update_user_status), group=2)  # filters.ChatType.SUPERGROUP to get only chat messages
            self.application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_update_user_status), group=2)

            # checking if user says thank you.
            self.application.add_handler(MessageHandler(filters.TEXT, tg_thankyou), group=3)

            # reporting
            self.application.add_handler(CommandHandler(['report', 'r'], tg_report, filters.ChatType.SUPERGROUP), group=4)
            self.application.add_handler(CommandHandler(['warn', 'w'], tg_warn, filters.ChatType.SUPERGROUP), group=4)

            self.application.add_handler(CommandHandler(['set_rating'], tg_set_rating, filters.ChatType.SUPERGROUP), group=4)
            self.application.add_handler(CommandHandler(['set_report'], tg_set_report, filters.ChatType.SUPERGROUP), group=4)

            self.application.add_handler(CommandHandler(['get_rating', 'gr'], tg_get_rating, filters.ChatType.SUPERGROUP), group=4)

            # Add a handler for chat join requests
            self.application.add_handler(ChatJoinRequestHandler(tg_join_request), group=5)

            self.application.add_handler(CommandHandler(['ban', 'b'], tg_ban, filters.ChatType.SUPERGROUP), group=6)
            self.application.add_handler(CommandHandler(['gban', 'g', 'gb'], tg_gban), group=6)

            self.application.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, tg_spam_check), group=7)

            # self.application.add_handler(MessageHandler(filters.TEXT, tg_ai_spam_check), group=8)
            self.application.add_handler(MessageHandler(filters.TEXT & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP), tg_new_spamcheck), group=8)

            self.application.add_handler(CommandHandler(['pin', 'p'], tg_pin, filters.ChatType.SUPERGROUP), group=9)
            self.application.add_handler(CommandHandler(['unpin', 'up'], tg_unpin, filters.ChatType.SUPERGROUP), group=9)

            self.application.add_handler(CommandHandler(['help', 'h'], tg_help), group=10)

            self.application.add_handler(MessageHandler(filters.TEXT, tg_auto_reply), group=11)

            # Set up the graceful shutdown mechanism
            signal.signal(signal.SIGTERM, self.signal_handler)

            # Start the Bot
            self.application.run_polling()
        except Exception as e:
            logger.error(f"Error: {traceback.format_exc()}")

if __name__ == '__main__':
    manager = BotManager()
    manager.run()
