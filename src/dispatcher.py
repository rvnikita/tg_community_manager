import sentry_sdk
import os

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    traces_sample_rate=1.0,  # or lower in prod
    profile_session_sample_rate=1.0,    # this is the new way, not profiles_sample_rate!
    profile_lifecycle="trace",          # automatic profiling during spans
)

import functools

def sentry_profile(name=None):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            tx_name = name or func.__name__
            with sentry_sdk.start_transaction(name=tx_name):
                return await func(*args, **kwargs)
        return wrapper
    return decorator




from telegram import Bot, ChatPermissions
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ChatJoinRequestHandler, ApplicationBuilder, JobQueue
from telegram.request import HTTPXRequest
from telegram.error import TelegramError
from datetime import datetime, timedelta, timezone
import openai
import traceback
import re
import asyncio
import aiohttp
import ssl
import signal
import sys
import json
from re import findall
import logging

from langdetect import detect
import langdetect
from datetime import datetime, timedelta, timezone

import src.logging_helper as logging_helper
import src.openai_helper as openai_helper
import src.chat_helper as chat_helper
import src.db_helper as db_helper
import src.user_helper as user_helper
import src.rating_helper as rating_helper
import src.reporting_helper as reporting_helper
import src.message_helper as message_helper
import src.spamcheck_helper as spamcheck_helper
import src.spamcheck_helper_raw as spamcheck_helper_raw
import helpers.spamcheck_helper_raw_structure as spamcheck_helper_raw_structure
import src.helpers.embeddings_reply_helper as embeddings_reply_helper

logger = logging_helper.get_logger()

logger.info(f"Starting {__file__} in {os.getenv('ENV_BOT_MODE')} mode at {os.uname()}")

bot = Bot(os.getenv('ENV_BOT_KEY'),
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

########################

@sentry_profile()
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

@sentry_profile()
async def tg_report(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        if not message or not message.reply_to_message:
            logger.info("Report command without a message to reply to.")
            return

        reported_message_id = message.reply_to_message.message_id
        reported_user_id = message.reply_to_message.from_user.id
        # Determine the content of the reported message: Use text if available, otherwise use caption
        reported_message_content = message.reply_to_message.text or message.reply_to_message.caption

        reporting_user_id = message.from_user.id

        if message:
            await chat_helper.schedule_message_deletion(chat_id, message.message_id, message.from_user.id, trigger_id=reported_message_id, delay_seconds=2 * 60 * 60)  # use reported_message_id as trigger_id

        chat_administrators = await chat_helper.get_chat_administrators(context.bot, chat_id)
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

        # Inform admins about the report
        await chat_helper.send_message_to_admin(
            context.bot, 
            chat_id, 
            f"User {reported_user_mention} has been reported by {user_helper.get_user_mention(reporting_user_id, chat_id)} in chat {chat_mention} {report_sum}/{number_of_reports_to_ban} times.\nReported message: {reported_message_content}"
        )
        logger.info(
            f"User {reported_user_id} has been reported by {user_helper.get_user_mention(reporting_user_id, chat_id)} in chat {chat_id} {report_sum}/{number_of_reports_to_ban} times. Reported message: {reported_message_content}"
        )

        if report_sum >= number_of_reports_to_ban:
            # Increase rating for all users who reported this user
            reporting_user_ids = await reporting_helper.get_reporting_users(chat_id, reported_user_id)
            bot_info = await bot.get_me()
            await rating_helper.change_rating(reporting_user_ids, bot_info.id, chat_id, 1, delete_message_delay=120)

            await chat_helper.ban_user(context.bot, chat_id, reported_user_id)
            await chat_helper.delete_message(context.bot, chat_id, reported_message_id)
            await chat_helper.send_message(context.bot, chat_id, f"User {reported_user_mention} has been banned due to {report_sum}/{number_of_reports_to_ban} reports.", delete_after=120)
            await chat_helper.send_message_to_admin(
                context.bot, 
                chat_id, 
                f"User {reported_user_mention} has been banned in chat {chat_mention} due to {report_sum}/{number_of_reports_to_ban} reports. \nReported message: {reported_message_content}"
            )

            # Delete all messages from scheduled deletion with trigger_id = reported_message_id
            await chat_helper.delete_scheduled_messages(bot, chat_id, trigger_id=reported_message_id)

            # Log the ban action
            message_helper.insert_or_update_message_log(
                chat_id=chat_id,
                message_id=reported_message_id,
                user_id=reported_user_id,
                user_nickname=reported_user_mention,
                user_current_rating=rating_helper.get_rating(reported_user_id, chat_id),
                message_content=reported_message_content,
                action_type="report & ban",
                reporting_id=reporting_user_id,
                reporting_id_nickname=user_helper.get_user_mention(reporting_user_id, chat_id),
                reason_for_action=f"User {reported_user_mention} was banned in chat {chat_mention} due to {report_sum}/{number_of_reports_to_ban} reports.",
                is_spam=True
            )

        elif report_sum >= number_of_reports_to_warn:
            await chat_helper.warn_user(context.bot, chat_id, reported_user_id)
            await chat_helper.mute_user(context.bot, chat_id, reported_user_id, reason="User has been warned and muted due to multiple reports.")
            await chat_helper.send_message(
                context.bot, 
                chat_id, 
                f"User {reported_user_mention} has been warned and muted due to {report_sum}/{number_of_reports_to_ban} reports.", 
                reply_to_message_id=reported_message_id, 
                delete_after=120
            )
            await chat_helper.send_message_to_admin(
                context.bot, 
                chat_id, 
                f"User {reported_user_mention} has been warned and muted in chat {chat_mention} due to {report_sum}/{number_of_reports_to_ban} reports. \nReported message: {reported_message_content}"
            )
        else:
            user_has_been_reported_message = await chat_helper.send_message(
                context.bot, 
                chat_id, 
                f"User {reported_user_mention} has been reported {report_sum}/{number_of_reports_to_ban} times."
            )
            await chat_helper.schedule_message_deletion(
                chat_id, 
                message_id=user_has_been_reported_message.message_id, 
                user_id=reported_user_id, 
                trigger_id=reported_message_id
            )

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

from datetime import datetime, timezone
from sqlalchemy import func
import src.db_helper as db_helper
from src.user_helper import get_user_id
import src.chat_helper as chat_helper
import src.rating_helper as rating_helper

@sentry_profile()
async def tg_info(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        #delete the command message after 120 seconds
        asyncio.create_task(chat_helper.delete_message(context.bot, chat_id, message.message_id, delay_seconds=60))

        # determine target_user_id
        if message.reply_to_message:
            target_user_id = message.reply_to_message.from_user.id
        else:
            parts = message.text.split()
            target_user_id = None
            if len(parts) >= 2:
                arg = parts[1]
                if arg.startswith('@'):
                    target_user_id = get_user_id(arg[1:])
                elif arg.isdigit():
                    target_user_id = int(arg)

        if not target_user_id:
            await chat_helper.send_message(
                context.bot, chat_id,
                "Please specify a user by replying, @username, or user_id.",
                reply_to_message_id=message.message_id,
                delete_after=120
            )
            return

        # fetch and extract user fields inside session
        with db_helper.session_scope() as session:
            u = session.query(db_helper.User).filter_by(id=target_user_id).first()
            if not u:
                await chat_helper.send_message(
                    context.bot, chat_id,
                    f"No data for user {target_user_id}.",
                    reply_to_message_id=message.message_id,
                    delete_after=120
                )
                return
            created_at = u.created_at or datetime.now(timezone.utc)
            first_name = u.first_name or ''
            last_name = u.last_name or ''
            username = u.username

        now = datetime.now(timezone.utc)
        days_since = (now - created_at).days
        rating = rating_helper.get_rating(target_user_id, chat_id)

        # count messages
        with db_helper.session_scope() as session:
            chat_count = session.query(func.count(db_helper.Message_Log.id)) \
                                .filter(db_helper.Message_Log.user_id == target_user_id,
                                        db_helper.Message_Log.chat_id == chat_id) \
                                .scalar() or 0
            total_count = session.query(func.count(db_helper.Message_Log.id)) \
                                 .filter(db_helper.Message_Log.user_id == target_user_id) \
                                 .scalar() or 0

        full_name = (first_name + ' ' + last_name).strip() or '[no name]'

        info_text = (
            f"👤 {'@'+username if username else '[no username]'}\n"
            f"🪪 {full_name}\n"
            f"📅 Joined: {days_since} days ago\n"
            f"⭐ Rating: {rating}\n"
            f"✉️ Messages (this chat): {chat_count}\n"
            f"✉️ Messages (all chats): {total_count}"
        )

        await chat_helper.send_message(
            context.bot, chat_id, info_text,
            reply_to_message_id=message.message_id,
            delete_after=200
        )
    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")



@sentry_profile()
async def tg_offtop(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message
        admin_ids = [admin.user.id for admin in await chat_helper.get_chat_administrators(bot, chat_id)]

        await chat_helper.delete_message(bot, chat_id, message.message_id, delay_seconds=120)  # clean up the command message

        # TODO:MED: We should find the way how to identify admin if he answes from channel
        if message.from_user.id not in admin_ids:
            await chat_helper.send_message(bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after=120)
            return

        if not message.reply_to_message:
            await chat_helper.send_message(bot, chat_id, "Reply to a message to warn the user.", reply_to_message_id=message.message_id, delete_after=120)
            return

        reason = ' '.join(message.text.split()[1:]) or "You've been warned for offtopic by an admin."
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
                    await rating_helper.change_rating(user_id, bot_info.id, chat_id, 1, delete_message_delay=120)

                return

            await chat_helper.send_message(bot, chat_id, f"{warned_user_mention}, you've been warned {warn_count}/{number_of_reports_to_ban} times. Reason: {reason}", reply_to_message_id=warned_message_id)
            await chat_helper.delete_message(bot, chat_id, warned_message_id)
            await chat_helper.send_message_to_admin(bot, chat_id, f"{warning_admin_mention} warned {warned_user_mention} in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {reason}. Total Warnings: {warn_count}/{number_of_reports_to_ban}")

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

@sentry_profile()
async def tg_set_report(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        # Verify if the command issuer is an administrator
        chat_administrators = await chat_helper.get_chat_administrators(context.bot, chat_id)
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


@sentry_profile()
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

@sentry_profile()
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

@sentry_profile()
async def tg_warn(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message
        admin_ids = [admin.user.id for admin in await chat_helper.get_chat_administrators(bot, chat_id)]

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


@sentry_profile()
async def tg_ban(update, context):
    try:
        with db_helper.session_scope() as db_session:
            message = update.message
            chat_id = update.effective_chat.id
            ban_user_id = None

            await chat_helper.delete_message(bot, chat_id, message.message_id)  # clean up the command message

            # Check if the command was sent by an admin of the chat
            chat_administrators = await chat_helper.get_chat_administrators(bot, chat_id)

            # TODO:MED: We should find the way how to identify admin if he answers from channel
            if message.from_user.id not in [admin.user.id for admin in chat_administrators]:
                await chat_helper.send_message(bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after=120)
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
            else:  # Check if a user is mentioned in the command message as a reply to message
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

            # Determine the content of the reported message: Use text if available, otherwise use caption
            reported_message_content = message.reply_to_message.text or message.reply_to_message.caption

            # Ban the user
            await chat_helper.ban_user(bot, chat_id, ban_user_id)

            # Log the ban action
            message_helper.insert_or_update_message_log(
                chat_id=chat_id,
                message_id=message.reply_to_message.message_id,
                user_id=ban_user_id,
                user_nickname=user_helper.get_user_mention(ban_user_id, chat_id),
                user_current_rating=rating_helper.get_rating(ban_user_id, chat_id),
                message_content=reported_message_content,
                action_type="ban",
                reporting_id=message.from_user.id,
                reporting_id_nickname=user_helper.get_user_mention(message.from_user.id, chat_id),
                reason_for_action=f"User {user_helper.get_user_mention(ban_user_id, chat_id)} was banned in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {message.text}",
                is_spam=False
            )

            await chat_helper.send_message(bot, chat_id, f"User {user_helper.get_user_mention(ban_user_id, chat_id)} has been banned.", delete_after=120)

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

@sentry_profile()
async def tg_spam(update, context):
    try:
        message = update.message
        chat_id = update.effective_chat.id

        await chat_helper.delete_message(bot, chat_id, message.message_id)  # clean up the command message

        # 1. Determine target user.
        target_user_id = None
        command_parts = message.text.split()
        if message.reply_to_message:
            target_user_id = message.reply_to_message.from_user.id
            await chat_helper.delete_message(bot, chat_id, message.reply_to_message.message_id)

        elif len(command_parts) > 1:
            if command_parts[1].isdigit():
                target_user_id = int(command_parts[1])
            elif command_parts[1].startswith('@'):
                target_user_id = user_helper.get_user_id(username=command_parts[1][1:])
            else:
                await chat_helper.send_message(
                    context.bot,
                    chat_id,
                    "Invalid format. Use /spam @username or /spam user_id, or reply to a message.",
                    reply_to_message_id=message.message_id
                )
                return
        else:
            await chat_helper.send_message(
                context.bot,
                chat_id,
                "Please reply to a user's message or specify a user to spam.",
                reply_to_message_id=message.message_id
            )
            return

        # 2. Globally ban the user.
        await chat_helper.ban_user(
            context.bot,
            chat_id,
            target_user_id,
            global_ban=True,
            reason="Spam command issued by global admin"
        )

        # 3. Retrieve all message logs for the target user and update them.
        with db_helper.session_scope() as session:
            logs = session.query(db_helper.Message_Log).filter(
                db_helper.Message_Log.user_id == target_user_id
            ).all()
            logs_data = [
                {"chat_id": log.chat_id, "message_id": log.message_id}
                for log in logs
            ]
        for log_data in logs_data:
            message_helper.insert_or_update_message_log(
                chat_id=log_data["chat_id"],
                message_id=log_data["message_id"],
                user_id=target_user_id,
                is_spam=True,
                manually_verified=True
            )

        # 4. For messages less than 24 hours old, delete them from all chats.
        cutoff = datetime.now() - timedelta(hours=24)
        with db_helper.session_scope() as session:
            recent_logs = session.query(db_helper.Message_Log).filter(
                db_helper.Message_Log.user_id == target_user_id,
                db_helper.Message_Log.created_at >= cutoff
            ).all()
            recent_logs_data = [
                {"chat_id": log.chat_id, "message_id": log.message_id}
                for log in recent_logs
            ]
        for log_data in recent_logs_data:
            try:
                await chat_helper.delete_message(context.bot, log_data["chat_id"], log_data["message_id"])
            except Exception as exc:
                logger.error(f"Error deleting message {log_data['message_id']} in chat {log_data['chat_id']}: {exc}")

        target_mention = user_helper.get_user_mention(target_user_id, chat_id)
    except Exception as e:
        update_str = json.dumps(
            update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'},
            indent=4, sort_keys=True, default=str
        )
        logger.error(f"Error in tg_spam: {traceback.format_exc()} | Update: {update_str}")
        await chat_helper.send_message(
            context.bot,
            chat_id,
            "An error occurred while processing the spam command.",
            reply_to_message_id=message.message_id
        )


@sentry_profile()
async def tg_unspam(update, context):
    try:
        message = update.message
        chat_id = update.effective_chat.id

        # Only allow global admin to run this command.
        if message.from_user.id != int(os.getenv('ENV_BOT_ADMIN_ID')):
            await chat_helper.send_message(
                context.bot,
                chat_id,
                "You must be a global admin to use this command.",
                reply_to_message_id=message.message_id
            )
            return

        # Determine target user: use the replied message if available; otherwise, expect an argument.
        target_user_id = None
        command_parts = message.text.split()
        if message.reply_to_message:
            target_user_id = message.reply_to_message.from_user.id
        elif len(command_parts) > 1:
            if command_parts[1].isdigit():
                target_user_id = int(command_parts[1])
            elif command_parts[1].startswith('@'):
                target_user_id = user_helper.get_user_id(username=command_parts[1][1:])
            else:
                await chat_helper.send_message(
                    context.bot,
                    chat_id,
                    "Invalid format. Use /unspam @username or /unspam user_id, or reply to a message.",
                    reply_to_message_id=message.message_id
                )
                return
        else:
            await chat_helper.send_message(
                context.bot,
                chat_id,
                "Please reply to a user's message or specify a user to unspam.",
                reply_to_message_id=message.message_id
            )
            return

        # Step 1: Unban the user from all chats.
        await chat_helper.unban_user(context.bot, chat_id, target_user_id, global_unban=True)
        logger.info(f"User {target_user_id} has been unbanned globally.")

        # Step 2: Unmute the user in all chats.
        await chat_helper.unmute_user(context.bot, chat_id, target_user_id, global_unmute=True)
        logger.info(f"User {target_user_id} has been unmuted globally.")

        # Step 3: Update all message logs for the user.
        # Materialize the log values from a session before closing it.
        with db_helper.session_scope() as session:
            logs = session.query(db_helper.Message_Log).filter(
                db_helper.Message_Log.user_id == target_user_id,
                db_helper.Message_Log.manually_verified == False
            ).all()
            logs_data = [
                {"chat_id": log.chat_id, "message_id": log.message_id}
                for log in logs
            ]
        # Now update each log without needing the detached ORM objects.
        for log_data in logs_data:
            message_helper.insert_or_update_message_log(
                chat_id=log_data["chat_id"],
                message_id=log_data["message_id"],
                is_spam=False,
                manually_verified=True
            )

        target_mention = user_helper.get_user_mention(target_user_id, chat_id)
        await chat_helper.send_message(
            context.bot,
            chat_id,
            f"User {target_mention} has been unspammed (unbanned, unmuted, and message logs updated).",
            reply_to_message_id=message.message_id
        )
    except Exception as e:
        update_str = json.dumps(
            update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'},
            indent=4, sort_keys=True, default=str
        )
        logger.error(f"Error in tg_unspam: {traceback.format_exc()} | Update: {update_str}")
        await chat_helper.send_message(
            context.bot,
            chat_id,
            "An error occurred while processing the unspam command.",
            reply_to_message_id=message.message_id
        )


@sentry_profile()
async def tg_gban(update, context):
    try:
        with db_helper.session_scope() as db_session:
            message = update.message
            chat_id = update.effective_chat.id
            ban_user_id = None
            ban_chat_id = None
            ban_reason = None

            # Check if the command was sent by a global admin of the bot
            # TODO:MED: We should find the way how to identify admin if he answers from channel
            if message.from_user.id != int(os.getenv('ENV_BOT_ADMIN_ID')):
                await message.reply_text("You must be a global bot admin to use this command.")
                return

            await chat_helper.delete_message(bot, chat_id, message.message_id)  # clean up the command message

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
            elif chat_id == int(os.getenv('ENV_INFO_CHAT_ID')) or chat_id == int(os.getenv('ENV_ERROR_CHAT_ID')):
                ban_reason = f"User was globally banned by {message.text} command in info chat. Message: {message.reply_to_message.text}"
                if not message.reply_to_message:
                    await message.reply_text("Please reply to a message containing usernames to ban.")
                    return
                username_list = re.findall('@(\w+)', message.reply_to_message.text)  # extract usernames from the reply_to_message
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
            else:  # Check if a user is mentioned in the command message as a reply to message
                ban_reason = f"User was globally banned by {message.text} command in {await chat_helper.get_chat_mention(bot, chat_id)}. Message: {message.reply_to_message.text}"
                ban_chat_id = chat_id  # We need to ban in the same chat as the command was sent

                if not message.reply_to_message:
                    await message.reply_text("Please reply to a user's message to ban them.")
                    return
                ban_user_id = message.reply_to_message.from_user.id

                await chat_helper.delete_message(bot, chat_id, message.reply_to_message.message_id)

            # Determine the content of the reported message: Use text if available, otherwise use caption
            reported_message_content = message.reply_to_message.text or message.reply_to_message.caption

            # Ban the user and add them to the banned_users table
            await chat_helper.ban_user(bot, ban_chat_id, ban_user_id, True, reason=ban_reason)

            # Log the ban action
            message_helper.insert_or_update_message_log(
                chat_id=chat_id,
                message_id=message.reply_to_message.message_id,
                user_id=ban_user_id,
                user_nickname=user_helper.get_user_mention(ban_user_id, chat_id),
                user_current_rating=rating_helper.get_rating(ban_user_id, chat_id),
                message_content=reported_message_content,
                action_type="gban",
                reporting_id=message.from_user.id,
                reporting_id_nickname=user_helper.get_user_mention(message.from_user.id, chat_id),
                reason_for_action=f"User {user_helper.get_user_mention(ban_user_id, chat_id)} was banned in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {message.text}",
                manually_verified=False
            )


    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")



#TODO:MED: May be we need to make it more complicated (e.g. with ai embeddings) and move big part of it to separate auto_deply_helper
@sentry_profile()
async def tg_auto_reply(update, context):
    try:
        if update.message and update.message.text:
            chat_id = update.effective_chat.id
            message_text = update.message.text.lower()
        else:
            return  # Skip processing if there's no text message

        # Fetch auto replies that are not currently delayed
        auto_replies = await chat_helper.get_auto_replies(chat_id, filter_delayed=True)

        for auto_reply in auto_replies:
            try:
                triggers_raw = auto_reply['trigger']
                triggers = json.loads(triggers_raw)
                triggers = [trigger.lower() for trigger in triggers]
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse auto-reply trigger: {auto_reply['trigger']}")
                continue

            matched = False
            for trigger in triggers:
                if trigger.startswith("#"):
                    # Match hashtags using simple space split (handles "#успех", not "#успех!" or "#успех.")
                    if trigger in message_text.split():
                        matched = True
                        break
                else:
                    if findall(r'\b' + re.escape(trigger) + r'\b', message_text):
                        matched = True
                        break

            if matched:
                await chat_helper.send_message(
                    context.bot, chat_id, auto_reply['reply'],
                    reply_to_message_id=update.message.message_id
                )
                await chat_helper.update_last_reply_time_and_increment_count(
                    chat_id, auto_reply['id'], datetime.now(timezone.utc)
                )
                logger.info(f"Auto-reply sent in chat {chat_id} for triggers '{', '.join(triggers)}': {auto_reply['reply']}")
                break  # Stop after first match to avoid sending multiple replies

    except Exception as error:
        logger.error(f"tg_auto_reply error: {traceback.format_exc()}")

# import pymorphy2
# from nltk.stem import WordNetLemmatizer
# from langdetect import detect
# import json
# from datetime import datetime, timezone
# import traceback

# morph = pymorphy2.MorphAnalyzer()
# lemmatizer = WordNetLemmatizer()

# #lemmatized version of tg_auto_reply (temporary)
# #TODO:MED: we should store lemmed versions of triggers in DB for performance
# @sentry_profile()
# async def tg_lemm_auto_reply(update, context):
#     try:
#         if update.message and update.message.text:
#             chat_id = update.effective_chat.id
#             message_text = update.message.text
#             message_lemmas = lemmatizer_helper.lemmatize_words(message_text)
#         else:
#             return

#         auto_replies = await chat_helper.get_auto_replies(chat_id, filter_delayed=True)
#         for auto_reply in auto_replies:
#             try:
#                 triggers_raw = auto_reply["trigger"]
#                 triggers = json.loads(triggers_raw)
#                 # TODO:MED cache lemmatized triggers in DB for performance
#                 trigger_lemmas = set(lemmatizer_helper.lemmatize_single(trigger) for trigger in triggers)
#             except json.JSONDecodeError:
#                 logger.warning(f"Failed to parse auto-reply trigger: {auto_reply['trigger']}")
#                 continue

#             if trigger_lemmas & message_lemmas:
#                 await chat_helper.send_message(
#                     context.bot,
#                     chat_id,
#                     auto_reply["reply"],
#                     reply_to_message_id=update.message.message_id,
#                 )
#                 await chat_helper.update_last_reply_time_and_increment_count(
#                     chat_id, auto_reply["id"], datetime.now(timezone.utc)
#                 )
#                 logger.info(
#                     f"Auto-reply sent in chat {chat_id} for triggers '{', '.join(triggers)}': {auto_reply['reply']}"
#                 )
#                 break

#     except Exception as error:
#         logger.error(f"tg_auto_reply error: {traceback.format_exc()}")


import src.helpers.embeddings_reply_helper as embeddings_reply_helper

@sentry_profile()
async def tg_embeddings_auto_reply(update, context):
    try:
        logger.info(f"🥶 tg_embeddings_auto_reply called with update: {update}")
        if not (update.message and update.message.text):
            return

        chat_id = update.effective_chat.id
        message_text = update.message.text

        message_embedding = await openai_helper.generate_embedding(message_text)

        logger.info(f"🥶 tg_embeddings_auto_reply message_embedding: {message_embedding}")

        row = embeddings_reply_helper.find_best_embeddings_trigger(chat_id, message_embedding)

        logger.info(f"🥶 tg_embeddings_auto_reply found row: {row}")
        
        if not row:
            return

        content = embeddings_reply_helper.get_content_by_id(row["content_id"])
        if not content:
            return

        await embeddings_reply_helper.send_embeddings_reply(
            context.bot, chat_id, content["reply"], update.message.message_id, content
        )

    except Exception:
        logger.error(f"tg_embeddings_auto_reply error: {traceback.format_exc()}")


@sentry_profile()
async def tg_handle_forwarded_messages(update, context):
    try:
        message = update.message
        if not message:
            return

        # Check if the user is an admin; if so, don't process their messages
        chat_administrators = await chat_helper.get_chat_administrators(context.bot, message.chat.id)
        is_admin = any(admin.user.id == message.from_user.id for admin in chat_administrators)
        if is_admin:
            return

        # Check if the feature is enabled for the chat
        if not chat_helper.get_chat_config(message.chat.id, "handle_forwarded_messages"):
            return

        # Safely access 'forward_from_chat' using getattr
        forward_from_chat = getattr(message, 'forward_from_chat', None)
        if forward_from_chat and forward_from_chat.type == 'channel':
            # Delete the original message
            await chat_helper.delete_message(context.bot, message.chat.id, message.message_id)

            # Prepare the new message content using your user_helper.get_user_mention function
            user_mention = user_helper.get_user_mention(message.from_user.id, message.chat.id)
            original_content = message.text or message.caption or ""

            new_message = f"{user_mention} shared: {original_content}"

            # Send the new message as admin without specifying parse_mode
            await context.bot.send_message(
                chat_id=message.chat.id,
                text=new_message
            )

            # Log the action
            logger.info(
                f"Forwarded message from channel handled. "
                f"User: {user_mention}, Chat ID: {message.chat.id}, Original Message ID: {message.message_id}"
            )
    except Exception as e:
        logger.error(f"Error in tg_handle_forwarded_messages: {traceback.format_exc()}")




@sentry_profile()
async def tg_log_message(update, context):
    try:
        message = update.message
        if message:
            user_id = message.from_user.id
            user_nickname = message.from_user.username or message.from_user.first_name
            chat_id = message.chat.id
            message_content = message.text or message.caption or "Non-text message"
            message_id = message.message_id
            user_current_rating = rating_helper.get_rating(user_id, chat_id)
            
            action_type = "message"
            reason_for_action = "Regular message"
            is_forwarded = None

            # Check if 'forward_origin' exists and if it contains the necessary data
            if hasattr(message, 'forward_origin') and message.forward_origin and hasattr(message.forward_origin, 'sender_user'):
                forward_from = message.forward_origin.sender_user
                reason_for_action = f"Forwarded message from {forward_from.first_name} {forward_from.last_name} (ID: {forward_from.id})"
                action_type = "forward"
                is_forwarded = True
            else:
                pass
                # logger.info("No 'forward_origin' in message or sender_user data is missing.")

            #TODO:LOW: Maybe we don't need to calculate embedding and insert it in DB here as we will recalculate it later in tg_ai_spamcheck. But we should be careful as it seems like sometimes tg_ai_spamcheck is not called (or maybe called but not updating the message log in DB is there is something wrong with the probability calculation. That happens if "ai_spamcheck_enabled": false in chat config)
            embedding =await openai_helper.generate_embedding(message_content)


            # Log the message, treating forwarded messages differently if needed
            message_log_id = message_helper.insert_or_update_message_log(
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_nickname=user_nickname,
                user_current_rating=user_current_rating,
                message_content=message_content,
                action_type=action_type,
                reporting_id=user_id,
                reporting_id_nickname=user_nickname,
                reason_for_action=reason_for_action,
                is_spam=False,
                embedding=embedding,
                manually_verified=False,
                reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None,
                is_forwarded=is_forwarded,
                raw_message=update.message.to_dict() if hasattr(update.message, 'to_dict') else None
            )

            logger.debug(f"Message logged with ID: {message_log_id} in chat {chat_id}.")


            if not message_log_id:
                update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
                logger.error(f"Failed to log the message in the database: {traceback.format_exc()} | Update: {update_str}")
    except Exception as error:
        logger.error(f"Error: {traceback.format_exc()}")




@sentry_profile()
async def tg_spam_check(update, context):
    try:
        message = update.message if update.message else update.edited_message

        #check if user is admin so don't check spam for them
        chat_administrators = await chat_helper.get_chat_administrators(context.bot, message.chat.id)
        is_admin = any(admin.user.id == message.from_user.id for admin in chat_administrators)
        if is_admin:
            return
        
        if message.from_user.id == 777000:  # Telegram's own bot TODO:MED: Maybe we need to check this differently as users could post through 777000 bot
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

@sentry_profile()
async def tg_ai_spamcheck(update, context):
    """
    ML-based spam detector with per-chat configuration.

    Chat-level settings (chat_helper.get_chat_config):
        • ai_spamcheck_enabled      – bool
        • ai_spamcheck_engine       – "legacy" | "raw"   (default = "legacy")
        • antispam_delete_threshold – float              (default = 0.80)
        • antispam_mute_threshold   – float              (default = 0.95)
    """
    try:
        message = update.message
        if not message or not message.from_user:
            return

        chat_id = message.chat.id
        user_id = message.from_user.id

        # ───────────── feature-toggle / admin-skip ─────────────
        if chat_helper.get_chat_config(chat_id, "ai_spamcheck_enabled") is not True:
            return
        if any(adm.user.id == user_id for adm in await chat_helper.get_chat_administrators(context.bot, chat_id)):
            return
        if user_id == 777000:
            return

        # ───────────── engine & thresholds ─────────────
        engine     = (chat_helper.get_chat_config(chat_id, "ai_spamcheck_engine") or "legacy").lower()
        engine     = engine if engine in ("legacy", "raw") else "legacy"
        delete_thr = float(chat_helper.get_chat_config(chat_id, "antispam_delete_threshold") or 0.80)
        mute_thr   = float(chat_helper.get_chat_config(chat_id, "antispam_mute_threshold")   or 0.95)

        # ───────────── message facts ─────────────
        text      = message.text or message.caption or "Non-text message"
        reply_to  = message.reply_to_message.message_id if message.reply_to_message else None
        forwarded = bool(getattr(message, "forward_from", None) or getattr(message, "forward_from_chat", None))

        # ───────────── model inference ─────────────
        loop = asyncio.get_event_loop()
        embedding = await openai_helper.generate_embedding(text)
        if engine == "raw":
            spam_prob = await spamcheck_helper_raw.predict_spam(
                user_id=user_id,
                chat_id=chat_id,
                message_text=text,
                raw_message=message.to_dict(),
                embedding=embedding,
            )
        elif engine == "raw_strucutre":
            spam_prob = await spamcheck_helper_raw_structure.predict_spam(
                user_id=user_id,
                chat_id=chat_id,
                message_text=text,
                raw_message=message.to_dict(),
                embedding=embedding,
            )
        else:
            spam_prob = await spamcheck_helper.predict_spam(
                user_id=user_id,
                chat_id=chat_id,
                message_content=text,
                embedding=embedding,
            )

        # ───────────── DB logging ─────────────
        message_log_id = message_helper.insert_or_update_message_log(
            chat_id                     = chat_id,
            message_id                  = message.message_id,
            user_id                     = user_id,
            user_nickname               = message.from_user.first_name,
            user_current_rating         = rating_helper.get_rating(user_id, chat_id),
            message_content             = text,
            action_type                 = "spam detection",
            reporting_id                = context.bot.id,
            reporting_id_nickname       = "rv_tg_community_bot",
            reason_for_action           = "Automated spam detection",
            is_spam                     = spam_prob >= delete_thr,
            manually_verified           = False,
            spam_prediction_probability = spam_prob,
            embedding                   = embedding
        )

        # ───────────── moderation action ─────────────
        action = "none"
        if spam_prob >= delete_thr:
            # always delete the offending message
            await chat_helper.delete_message(context.bot, chat_id, message.message_id)
            action = "delete"

            if spam_prob >= mute_thr:
                # gather *all* chat_ids where we’ve seen this user
                with db_helper.session_scope() as session:
                    rows = session.query(db_helper.User_Status.chat_id) \
                                  .filter_by(user_id=user_id) \
                                  .all()
                chat_ids = [cid for (cid,) in rows]

                # fallback to message logs if no statuses
                if not chat_ids:
                    with db_helper.session_scope() as session:
                        rows = session.query(db_helper.Message_Log.chat_id) \
                                      .filter(db_helper.Message_Log.user_id == user_id) \
                                      .distinct() \
                                      .all()
                    chat_ids = [cid for (cid,) in rows]

                try:
                    await chat_helper.mute_user(context.bot, chat_id, user_id, duration_in_seconds=21*24*60*60, global_mute=True, reason="AI spam detection")
                except Exception as e:
                    logger.error(f"global_mute failed for {user_id}: {e}")

                action = "delete+mute"

        # ───────────── pretty log ─────────────
        chat_name = await chat_helper.get_chat_mention(context.bot, chat_id)
        user_ment = user_helper.get_user_mention(user_id, chat_id)
        short_txt = (text[:200] + "…") if len(text) > 203 else text
        vis_emoji = "‼️" if action=="delete+mute" else "⚠️" if action=="delete" else "👌"

        log_lines = [
            "",
            "╔═ AI-Spamcheck",
            f"║ Probability  : {vis_emoji} {spam_prob:.5f}  (del≥{delete_thr}, mute≥{mute_thr})",
            f"║ Action       : {action}",
            f"║ User         : {user_ment}",
            f"║ Chat         : {chat_name} ({chat_id})",
            f"║ Engine       : {engine}",
            f"║ Msg-log-ID   : {message_log_id}",
            f"║ Fwd / Reply  : forwarded={forwarded}  reply_to={reply_to}",
            f"╚═ Content     : {short_txt}",
            f"      ↳ message_log_id={message_log_id}",
            f"      ↳ raw_message={message.to_dict() if hasattr(message, 'to_dict') else None}",
        ]
        logger.info("\n".join(log_lines))

    except Exception:
        logger.error(
            f"Error processing AI spamcheck | chat_id={update.effective_chat.id if update.effective_chat else 'N/A'} | "
            f"user_id={update.effective_user.id if update.effective_user else 'N/A'} | "
            f"traceback={traceback.format_exc()}"
        )



# BrightData (formerly Luminati) proxy credentials.
# Note: Adjust these values to match your actual BrightData account.
import asyncio

BRIGHTDATA_PROXY = "http://brd-customer-hl_cf9f8e6a-zone-residential_proxy1:k47qfcqxmwh3@brd.superproxy.io:22225"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

@sentry_profile()
async def tg_cas_spamcheck(update, context):
    if not update.message:
        return

    chat_id = update.effective_chat.id
    if not chat_helper.get_chat_config(chat_id, "cas_enabled", default=False):
        return

    checks = []
    if update.message.new_chat_members:
        for member in update.message.new_chat_members:
            checks.append((member.id, 0, member.username or member.first_name))
    else:
        msg = update.message
        checks.append((msg.from_user.id, msg.message_id, msg.from_user.username or msg.from_user.first_name))

    MAX_RETRIES = 3
    RETRY_DELAY = 1  # seconds

    async with aiohttp.ClientSession() as session:
        for user_id, message_id, nickname in checks:
            admins = await chat_helper.get_chat_administrators(context.bot, chat_id)
            if any(a.user.id == user_id for a in admins):
                continue
            
            #TODO:MED: Maybe I can cache value for short time (e.g. 5-10 second) or for long if we know that user is not CAS banned
            url = f"https://api.cas.chat/check?user_id={user_id}"
            resp = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = await session.get(url, proxy=BRIGHTDATA_PROXY, ssl=ssl_context)
                    if resp.status == 200:
                        break
                    elif resp.status == 502:
                        logger.warning(f"CAS API returned HTTP 502 for user {user_id}, attempt {attempt}/{MAX_RETRIES}")
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        else:
                            logger.error(f"CAS API failed after {MAX_RETRIES} retries for user {user_id}")
                            resp = None
                            break
                    else:
                        logger.error(f"CAS API returned HTTP {resp.status} for user {user_id}")
                        resp = None
                        break
                except Exception as e:
                    logger.error(f"CAS API request failed for user {user_id} on attempt {attempt}/{MAX_RETRIES}: {e}")
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    else:
                        resp = None
                        break

            if not resp or resp.status != 200:
                continue

            data = await resp.json()
            desc = data.get("description", "")

            if not data.get("ok", False):
                if "Record not found" in desc:
                    logger.info(f"CAS API no record for user {user_id}")
                else:
                    logger.info(f"CAS API not ok for user {user_id}: {desc}")
                continue

            if data.get("result", False):
                logger.info(f"CAS API found user {user_id} is CAS banned: {desc}")

                await chat_helper.mute_user(context.bot, chat_id, user_id, global_mute=True, reason="CAS spam check")
                message_helper.insert_or_update_message_log(
                    chat_id=chat_id,
                    message_id=message_id,
                    user_id=user_id,
                    user_nickname=nickname,
                    user_current_rating=rating_helper.get_rating(user_id, chat_id),
                    message_content=None if message_id == 0 else (update.message.text or update.message.caption),
                    action_type="CAS Spam Check" + (" (New Member)" if message_id == 0 else ""),
                    reporting_id=user_id,
                    reporting_id_nickname=nickname,
                    reason_for_action=f"User {user_id} is CAS banned. {desc}",
                    is_spam=True,
                    manually_verified=True,
                    embedding=None
                )
                logger.info(f"CAS check: muted user {user_id} in chat {chat_id}")



@sentry_profile()
async def tg_thankyou(update, context):
    try:
        msg = update.message
        # Require a reply-to and skip self-replies
        if not msg or not msg.reply_to_message or msg.reply_to_message.from_user.id == msg.from_user.id:
            return

        # Telegram forum topics send an invisible “forum_topic_created” reply; skip those
        if getattr(msg.reply_to_message, "forum_topic_created", None) is not None:
            return

        # Get the actual text to scan: either .text or .caption
        content = msg.text if msg.text is not None else msg.caption
        if not content:
            return

        # Load lists (might be None)
        like_words    = chat_helper.get_chat_config(msg.chat.id, "like_words")    or []
        dislike_words = chat_helper.get_chat_config(msg.chat.id, "dislike_words") or []

        for category, word_list in (("like_words", like_words), ("dislike_words", dislike_words)):
            for word in word_list:
                if not word:
                    continue
                if word.lower() in content.lower():
                    # Ensure the replied-to user exists in our DB
                    with db_helper.session_scope() as db_session:
                        target = msg.reply_to_message.from_user
                        user = db_session.query(db_helper.User).get(target.id)
                        if user is None:
                            user = db_helper.User(
                                id=target.id,
                                first_name=target.first_name or "",
                                last_name=target.last_name  or "",
                                username=target.username   or ""
                            )
                            db_session.add(user)
                        # Ensure the reacting user exists
                        reactor = msg.from_user
                        judge = db_session.query(db_helper.User).get(reactor.id)
                        if judge is None:
                            judge = db_helper.User(
                                id=reactor.id,
                                first_name=reactor.first_name or "",
                                last_name=reactor.last_name  or "",
                                username=reactor.username   or ""
                            )
                            db_session.add(judge)

                    # Apply rating change
                    if category == "like_words":
                        await rating_helper.change_rating(
                            msg.reply_to_message.from_user.id,
                            msg.from_user.id,
                            msg.chat.id,
                            +1,
                            msg.message_id,
                            delete_message_delay=5*60
                        )
                    else:  # dislike_words
                        await rating_helper.change_rating(
                            msg.reply_to_message.from_user.id,
                            msg.from_user.id,
                            msg.chat.id,
                            -1,
                            msg.message_id,
                            delete_message_delay=5*60
                        )
                    return
    except Exception as error:
        update_str = (
            json.dumps(update.to_dict(), indent=2, sort_keys=True)
            if hasattr(update, "to_dict")
            else "<no update.to_dict()>"
        )
        logger.error(f"Error in tg_thankyou: {traceback.format_exc()} | Update: {update_str}")


@sentry_profile()
async def tg_set_rating(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        # Check if the user is an administrator
        chat_administrators = await chat_helper.get_chat_administrators(context.bot, chat_id)
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

@sentry_profile()
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




@sentry_profile()
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


from telegram.ext import TypeHandler
async def debug_all_updates(update, context):
    logger.info(f"Update type: {type(update)} -- {update.to_dict()}")

#TODO:HIGH: THIS IS DEBUG TO UNDERSTAND WHY SPAMMERS JOIN ON NOT CAUGHT BY tg_new_member 
from telegram.ext import ChatMemberHandler

async def on_member_update(update, context):
    logger.info(f"on_member_update: {update.to_dict()}")
    # cmu = update.chat_member            # a ChatMemberUpdated
    # old, new = cmu.old_chat_member, cmu.new_chat_member

    # # Did they go from “left”/“kicked” → “member”?
    # if old.status in ("left", "kicked") and new.status in ("member", "restricted"):
    #     user = new.user
    #     chat = update.effective_chat

    #     logger.info(
    #         f"(DEBUG FOR SPAMMERS) New member {user.id} joined chat {chat.id} ({chat.title})"
    #     )
    

@sentry_profile()
async def tg_new_member(update, context):
    try:
        mute_new_users_duration = int(chat_helper.get_chat_config(update.effective_chat.id, "mute_new_users_duration", default=0))

        logger.info(f"New member {update.effective_user.id} joined chat {update.effective_chat.id} ({update.effective_chat.title})")

        delete_new_chat_members_message = chat_helper.get_chat_config(update.effective_chat.id, "delete_new_chat_members_message")

        if delete_new_chat_members_message == True:
            await chat_helper.delete_message(bot, update.message.chat.id, update.message.message_id)
            logger.info(f"Joining message deleted from chat {await chat_helper.get_chat_mention(bot, update.message.chat.id)} for user @{update.message.from_user.username} [{update.message.from_user.id}]")
                
        
        for new_member in update.message.new_chat_members:
            new_user_id = new_member.id

            with db_helper.session_scope() as db_session:
                # Check if the user is in the global ban list
                user_global_ban = db_session.query(db_helper.User_Global_Ban).filter(db_helper.User_Global_Ban.user_id == new_user_id).first()
                if user_global_ban is not None:
                    logger.info(f"User {new_user_id} is in global ban list. Kicking from chat {update.effective_chat.title} ({update.effective_chat.id})")
                    await chat_helper.ban_user(bot, update.effective_chat.id, new_user_id, reason="User is in global ban list")
                    await chat_helper.send_message(bot, update.effective_chat.id, f"User {new_user_id} is in global ban list. Kicking from chat {update.effective_chat.title} ({update.effective_chat.id})", delete_after=120)
                    continue  # Skip to the next new member

            if mute_new_users_duration > 0:
                await chat_helper.mute_user(bot, update.effective_chat.id, new_user_id, duration_in_seconds = mute_new_users_duration, reason="New user muted for spam check")
                logger.info(f"Muted new user {new_user_id} in chat {update.effective_chat.id} for {mute_new_users_duration} seconds.")

        welcome_message = chat_helper.get_chat_config(update.effective_chat.id, "welcome_message")

        if welcome_message:
            await chat_helper.send_message(bot, update.effective_chat.id, welcome_message, disable_web_page_preview=True)

    except Exception as e:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

@sentry_profile()
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
                    raw_user = update.message.new_chat_members[0].to_dict() if hasattr(update.message.new_chat_members[0], 'to_dict') else None
                    user_helper.db_upsert_user(update.message.new_chat_members[0].id, update.message.chat.id,  update.message.new_chat_members[0].username, datetime.now(), update.message.new_chat_members[0].first_name, update.message.new_chat_members[0].last_name, raw_user)
                else:
                    # TODO:HIGH: We need to rewrite this so we can also add full name
                    raw_user = update.message.from_user.to_dict() if hasattr(update.message.from_user, 'to_dict') else None
                    user_helper.db_upsert_user(update.message.from_user.id, update.message.chat.id, update.message.from_user.username, datetime.now(), update.message.from_user.first_name, update.message.from_user.last_name, raw_user=raw_user)

                #logger.info(f"User status updated for user {update.message.from_user.id} in chat {update.message.chat.id} ({update.message.chat.title})")

            delete_channel_bot_message = chat_helper.get_chat_config(update.message.chat.id, "delete_channel_bot_message") #delete messages that posted by channels, not users

            if delete_channel_bot_message == True:
                if update.message.from_user.is_bot == True and update.message.from_user.name == "@Channel_Bot":
                    #get all admins for this chat

                    delete_channel_bot_message_allowed_ids = chat_helper.get_chat_config(update.message.chat.id, "delete_channel_bot_message_allowed_ids")

                    if delete_channel_bot_message_allowed_ids is None or update.message.sender_chat.id not in delete_channel_bot_message_allowed_ids:
                        await chat_helper.delete_message(bot, update.message.chat.id, update.message.message_id)
                        await chat_helper.send_message(bot, update.message.chat.id, update.message.text)
                        logger.info(
                            f"Channel message deleted from chat {update.message.chat.title} ({update.message.chat.id}) for user @{update.message.from_user.username} ({update.message.from_user.id})")

    except Exception as e:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")

#We need this function to coordinate different function working with all text messages
@sentry_profile()
async def tg_wiretapping(update, context):
    try:
        tasks = [
            tg_handle_forwarded_messages(update, context),
            tg_log_message(update, context),
            tg_spam_check(update, context),
            tg_ai_spamcheck(update, context),
            tg_cas_spamcheck(update, context),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for handler, result in zip(
            ("forwarded", "log", "spam_check", "ai_spamcheck", "cas_spamcheck"),
            results
        ):
            if isinstance(result, Exception):
                logger.error(
                    f"Error in tg_wiretapping → {handler}: {traceback.format_exc()}",
                    exc_info=result
                )
    except Exception as e:
        update_str = json.dumps(
            update.to_dict() if hasattr(update, "to_dict") else {"info": "no to_dict"},
            indent=4, sort_keys=True, default=str
        )
        logger.error(f"Unhandled error in tg_wiretapping: {traceback.format_exc()} | Update: {update_str}")

class BotManager:
    def __init__(self):
        self.application = None

    def signal_handler(self, signum, frame):
        logger.error(f"Signal {signum} received, exiting...")
        if self.application:
            self.application.stop()
        sys.exit(0)

    def run(self):
        try:
            self.application = create_application()
            self.application.run_polling()
        except Exception as e:
            if "Event loop is closed" in str(e):
                logger.info("Received shutdown signal, exiting gracefully")
            else:
                logger.error(f"Error: {traceback.format_exc()}")

# temporary heartbeat function to check if the bot is alive
# TODO:MED: remove this function later
@sentry_profile()
async def tg_heartbeat(context):
    logger.info("💓 heartbeat")

async def global_error(update, context):
    logger.error("unhandled error", exc_info=context.error)

async def on_startup(app):
    logging.getLogger("apscheduler").setLevel(logging.WARNING) #get only warning messages from apscheduler

    # schedule heartbeat after application and JobQueue are ready
    app.job_queue.run_repeating(tg_heartbeat, interval=60, first=60)

@sentry_profile()
async def tg_ping(update, context):
    try:
        await update.message.reply_text("Pong!")
    except Exception as e:
        logger.error(f"Error in tg_ping: {traceback.format_exc()} | Update: {update.to_dict() if hasattr(update, 'to_dict') else 'N/A'}")

# ────────────────── Application Factory ──────────────────

def create_application():
    application = (
        ApplicationBuilder()
        .token(os.getenv("ENV_BOT_KEY"))
        .concurrent_updates(int(os.getenv("ENV_BOT_CONCURRENCY", "1")))
        .job_queue(JobQueue())
        .post_init(on_startup)
        .build()
    )
    application.add_error_handler(global_error)

    # Add handlers
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_new_member), group=0)
    application.add_handler(TypeHandler(object, debug_all_updates), group=1)
    application.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER), group=1)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_cas_spamcheck), group=1)
    application.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, tg_update_user_status), group=2)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, tg_update_user_status), group=2)
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION), tg_thankyou), group=3)
    application.add_handler(CommandHandler(["report", "r"], tg_report, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["warn", "w"], tg_warn, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["offtop", "o"], tg_offtop, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["set_rating"], tg_set_rating, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["set_report"], tg_set_report, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["get_rating", "gr"], tg_get_rating, filters.ChatType.GROUPS), group=4)
    application.add_handler(ChatJoinRequestHandler(tg_join_request), group=5)
    application.add_handler(CommandHandler(["ban", "b"], tg_ban, filters.ChatType.GROUPS), group=6)
    application.add_handler(CommandHandler(["gban", "g", "gb"], tg_gban), group=6)
    application.add_handler(CommandHandler(["spam", "s"], tg_spam), group=6)
    application.add_handler(CommandHandler(["unspam", "us"], tg_unspam), group=6)
    application.add_handler(
        MessageHandler(
            (filters.TEXT
             | (filters.PHOTO & filters.CAPTION)
             | (filters.VIDEO & filters.CAPTION)
             | filters.Document.ALL
             | filters.STORY
             | filters.FORWARDED)
            & filters.ChatType.GROUPS,
            tg_wiretapping,
        ),
        group=7,
    )
    application.add_handler(CommandHandler(["pin", "p"], tg_pin, filters.ChatType.GROUPS), group=9)
    application.add_handler(CommandHandler(["unpin", "up"], tg_unpin, filters.ChatType.GROUPS), group=9)
    application.add_handler(CommandHandler(["help", "h"], tg_help), group=10)
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION), tg_auto_reply), group=11)
    application.add_handler(CommandHandler(["info", "i"], tg_info), group=12)
    application.add_handler(CommandHandler(["ping", "p"], tg_ping), group=13)
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION), tg_embeddings_auto_reply), group=14)

    signal.signal(signal.SIGTERM, lambda s, f: application.stop())
    return application

class BotManager:
    def __init__(self):
        self.application = None

    def signal_handler(self, signum, frame):
        logger.error(f"Signal {signum} received, exiting...")
        if self.application:
            self.application.stop()
        sys.exit(0)

    def run(self):
        try:
            self.application = create_application()
            self.application.run_polling()
        except Exception as e:
            if "Event loop is closed" in str(e):
                logger.info("Received shutdown signal, exiting gracefully")
            else:
                logger.error(f"Error: {traceback.format_exc()}")

if __name__ == "__main__":
    manager = BotManager()
    manager.run()
