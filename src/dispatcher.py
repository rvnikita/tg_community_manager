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
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ChatJoinRequestHandler, ApplicationBuilder, JobQueue, MessageReactionHandler
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

import src.helpers.logging_helper as logging_helper
import src.helpers.openai_helper as openai_helper
import src.helpers.chat_helper as chat_helper
import src.helpers.db_helper as db_helper
import src.helpers.user_helper as user_helper
import src.helpers.rating_helper as rating_helper
import src.helpers.reporting_helper as reporting_helper
import src.helpers.message_helper as message_helper
import src.helpers.spamcheck_helper as spamcheck_helper
import src.helpers.spamcheck_helper_raw as spamcheck_helper_raw
import src.helpers.spamcheck_helper_raw_structure as spamcheck_helper_raw_structure
import src.helpers.embeddings_reply_helper as embeddings_reply_helpero
import src.helpers.cache_helper as cache_helper
import src.helpers.trigger_action_helper as trigger_action_helper

logger = logging_helper.get_logger()

logger.info(f"Starting {__file__} in {os.getenv('ENV_BOT_MODE')} mode at {os.uname()}")

bot = Bot(os.getenv('ENV_BOT_KEY'),
          request=HTTPXRequest(http_version="1.1"), #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556
          get_updates_request=HTTPXRequest(http_version="1.1")) #we need this to fix bug https://github.com/python-telegram-bot/python-telegram-bot/issues/3556)

########################

def extract_emoji_list(reaction_sequence):
    """Extract emoji strings from ReactionType objects."""
    if not reaction_sequence:
        return []
    emojis = []
    for reaction in reaction_sequence:
        if hasattr(reaction, 'emoji'):  # ReactionTypeEmoji only
            emojis.append(reaction.emoji)
    return emojis

@sentry_profile()
async def tg_help(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message
        user_id = message.from_user.id
        chat_type = update.effective_chat.type

        # User commands (available to everyone)
        user_commands = [
            "/report or /r - Report a message (reply to message)",
            "/get_rating or /gr - Get user rating (reply to message or specify @username)",
            "/help or /h - Show this help message",
            "/info or /i - Show bot information",
            "/ping - Check bot status"
        ]

        # Chat admin commands
        admin_commands = [
            "/warn or /w - Warn a user (reply to message)",
            "/offtop or /o - Warn for offtopic (reply to message)",
            "/ban or /b - Ban a user (reply to message or specify @username)",
            "/pin or /p - Pin a message (reply to message)",
            "/unpin or /up - Unpin a message (reply to message)",
            "/set_rating or /sr - Set user rating (@username or user_id, then rating)",
            "/set_report - Set report count (@username or user_id, then count)",
            "/ur or /unreport - Clear reports for a user (@username or reply to message)"
        ]

        # Global admin commands
        global_admin_commands = [
            "/gban or /g or /gb - Global ban across all chats",
            "/spam or /s - Mark user as spammer and ban globally",
            "/unspam or /us - Remove spam mark and unban user globally"
        ]

        # In group chats, always show only user commands (to avoid exposing admin commands publicly)
        # Admin commands are only shown in private/DM chats
        if chat_type in ['group', 'supergroup']:
            help_sections = ["<b>Available commands:</b>\n"]
            help_sections.append("<b>User commands:</b>")
            help_sections.extend(user_commands)
            help_sections.append("\n<i>For admin commands, please message me directly in DM.</i>")
            help_text = "\n".join(help_sections)

            await chat_helper.send_message(bot, chat_id, help_text, reply_to_message_id=message.message_id, delete_after=5 * 60, parse_mode='HTML')
            await chat_helper.schedule_message_deletion(chat_id, message.message_id, message.from_user.id, delay_seconds=5*60)
        else:
            # In private chats, show commands based on user permissions
            is_global_admin = user_id == int(os.getenv('ENV_BOT_ADMIN_ID'))

            help_sections = ["<b>Available commands:</b>\n"]
            help_sections.append("<b>User commands:</b>")
            help_sections.extend(user_commands)

            if is_global_admin:
                help_sections.append("\n<b>Admin commands:</b>")
                help_sections.extend(admin_commands)
                help_sections.append("\n<b>Global admin commands:</b>")
                help_sections.extend(global_admin_commands)

            help_text = "\n".join(help_sections)
            await chat_helper.send_message(bot, chat_id, help_text, parse_mode='HTML')

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
        if any(admin["user_id"] == reported_user_id for admin in chat_administrators):
            await chat_helper.send_message(context.bot, chat_id, "You cannot report an admin.", delete_after=120)
            return

        reporting_user_rating = rating_helper.get_rating(reporting_user_id, chat_id)
        user_rating_to_power_ratio = int(chat_helper.get_chat_config(chat_id, 'user_rating_to_power_ratio', default=0))
        report_power = 1 if user_rating_to_power_ratio == 0 else max(1, reporting_user_rating // user_rating_to_power_ratio)

        # Check if the reporting user is not an admin (if he is an admin he can report several times)
        if not any(admin["user_id"] == reporting_user_id for admin in chat_administrators):
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
            await chat_helper.delete_media_group_messages(context.bot, chat_id, message.reply_to_message)
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
import src.helpers.db_helper as db_helper
from src.helpers.user_helper import get_user_id
import src.helpers.chat_helper as chat_helper
import src.helpers.rating_helper as rating_helper

@sentry_profile()
async def tg_info(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message

        #delete the command message after 120 seconds
        asyncio.create_task(chat_helper.delete_message(context.bot, chat_id, message.message_id, delay_seconds=60))

        # determine target_user_id
        is_dm = update.effective_chat.type == "private"
        target_user_id = None

        if message.reply_to_message:
            reply_msg = message.reply_to_message
            # Check if it's a forwarded message - get original sender
            if hasattr(reply_msg, 'forward_origin') and reply_msg.forward_origin and hasattr(reply_msg.forward_origin, 'sender_user'):
                target_user_id = reply_msg.forward_origin.sender_user.id
            elif hasattr(reply_msg, 'forward_from') and reply_msg.forward_from:
                target_user_id = reply_msg.forward_from.id
            else:
                # Regular reply - get the message author
                target_user_id = reply_msg.from_user.id
        else:
            parts = message.text.split()
            if len(parts) >= 2:
                arg = parts[1]
                if arg.startswith('@'):
                    target_user_id = get_user_id(arg[1:])
                elif arg.isdigit():
                    target_user_id = int(arg)

        if not target_user_id:
            if is_dm:
                # In DM, show help message about available commands
                help_text = (
                    "Available commands in DM:\n\n"
                    "/info @username - Get user info by username\n"
                    "/info <user_id> - Get user info by ID\n"
                    "Forward a message + /info - Get info about original sender"
                )
                await chat_helper.send_message(
                    context.bot, chat_id,
                    help_text,
                    reply_to_message_id=message.message_id
                )
            else:
                await chat_helper.send_message(
                    context.bot, chat_id,
                    "Please specify a user by replying, @username, or user_id.",
                    reply_to_message_id=message.message_id,
                    delete_after=120
                )
            return

        # Get user info text using shared helper
        info_text = await user_helper.get_user_info_text(target_user_id, chat_id, is_dm=is_dm)

        # If user not found, the helper returns an error message
        if info_text.startswith("No data for user"):
            await chat_helper.send_message(
                context.bot, chat_id,
                info_text,
                reply_to_message_id=message.message_id,
                delete_after=120
            )
            return

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
        admin_ids = [admin["user_id"] for admin in await chat_helper.get_chat_administrators(bot, chat_id)]

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
                await chat_helper.delete_media_group_messages(bot, chat_id, message.reply_to_message)
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

            await chat_helper.send_message(
                bot,
                chat_id,
                f"{warned_user_mention}, you've been warned {warn_count}/{number_of_reports_to_ban} times. Reason: {reason}",
                reply_to_message_id=warned_message_id,
                delete_after=120,
            )
            await chat_helper.delete_media_group_messages(bot, chat_id, message.reply_to_message)
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
        is_admin = any(admin["user_id"] == message.from_user.id for admin in chat_administrators)
        if not is_admin:
            await chat_helper.send_message(context.bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after=120)
            return

        # Delete the command message
        await chat_helper.delete_message(context.bot, chat_id, message.message_id)

        command_parts = message.text.split()

        # Verify that the command is correctly formatted with at least two arguments
        if len(command_parts) < 3:
            await chat_helper.send_message(context.bot, chat_id, "Usage: /set_report [@username or user_id] [report_count]", delete_after=120)
            return

        # Parse the new report count
        try:
            new_report_count = int(command_parts[2])
        except ValueError:
            await chat_helper.send_message(context.bot, chat_id, "Invalid number for report count. Please specify an integer.", delete_after=120)
            return

        # Extract user ID using helper
        reported_user_id = user_helper.extract_user_id_from_command(message, command_parts, allow_reply=True)

        if reported_user_id is None:
            await chat_helper.send_message(context.bot, chat_id, "Invalid format. Use /set_report @username or /set_report user_id report_count.", delete_after=120)
            return

        # Set report count using helper
        success, current_reports, adjustment = await reporting_helper.set_report_count(
            chat_id,
            reported_user_id,
            message.from_user.id,
            new_report_count,
            "Adjusting with /set_report command"
        )

        if not success:
            await chat_helper.send_message(context.bot, chat_id, "Failed to set report count. Please try again.", delete_after=120)
            return

        await chat_helper.send_message(context.bot, chat_id, f"Report count for {user_helper.get_user_mention(reported_user_id, chat_id)} set to {new_report_count}.", delete_after=120)
    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error: {traceback.format_exc()} | Update: {update_str}")


@sentry_profile()
async def tg_ur(update, context):
    """Clear reports for a user - sets report count to 0"""
    try:
        chat_id = update.effective_chat.id
        message = update.message

        # Verify if the command issuer is an administrator
        chat_administrators = await chat_helper.get_chat_administrators(context.bot, chat_id)
        is_admin = any(admin["user_id"] == message.from_user.id for admin in chat_administrators)
        if not is_admin:
            await chat_helper.send_message(context.bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after=120)
            return

        # Delete the command message
        await chat_helper.delete_message(context.bot, chat_id, message.message_id)

        # Extract user ID using helper
        command_parts = message.text.split()
        reported_user_id = user_helper.extract_user_id_from_command(message, command_parts, allow_reply=True)

        if reported_user_id is None:
            await chat_helper.send_message(context.bot, chat_id, "Usage: /ur [@username or user_id] or reply to a message", delete_after=120)
            return

        # Clear reports using helper
        success, previous_count = await reporting_helper.clear_reports(chat_id, reported_user_id, message.from_user.id)

        if not success:
            await chat_helper.send_message(context.bot, chat_id, "Failed to clear reports. Please try again.", delete_after=120)
            return

        if previous_count == 0:
            await chat_helper.send_message(context.bot, chat_id, f"User {user_helper.get_user_mention(reported_user_id, chat_id)} has no reports.", delete_after=120)
            return

        await chat_helper.send_message(context.bot, chat_id, f"Reports cleared for {user_helper.get_user_mention(reported_user_id, chat_id)}. (Previous: {previous_count})", delete_after=120)
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
        with sentry_sdk.start_span(op="warn_admins", description="Get chat administrators"):
            chat_id = update.effective_chat.id
            message = update.message
            admin_ids = [admin["user_id"] for admin in await chat_helper.get_chat_administrators(bot, chat_id)]

        with sentry_sdk.start_span(op="warn_delete_command_msg", description="Delete command message"):
            await chat_helper.delete_message(bot, chat_id, message.message_id, delay_seconds=120)  # clean up the command message

        with sentry_sdk.start_span(op="warn_check_admin", description="Check admin privileges"):
            if message.from_user.id not in admin_ids:
                await chat_helper.send_message(bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after = 120)
                return

            if not message.reply_to_message:
                await chat_helper.send_message(bot, chat_id, "Reply to a message to warn the user.", reply_to_message_id=message.message_id, delete_after = 120)
                return

        with sentry_sdk.start_span(op="warn_parse", description="Parse warning reason and message"):
            reason = ' '.join(message.text.split()[1:]) or "You've been warned by an admin."
            warned_user_id = message.reply_to_message.from_user.id
            warned_message_id = message.reply_to_message.message_id

        with sentry_sdk.start_span(op="warn_db", description="DB report creation and warn count"):
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
                    with sentry_sdk.start_span(op="warn_ban", description="Ban and notify"):
                        await chat_helper.delete_media_group_messages(bot, chat_id, message.reply_to_message)
                        await chat_helper.ban_user(bot, chat_id, warned_user_id)
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

                with sentry_sdk.start_span(op="warn_notify", description="Warn and notify"):
                    await chat_helper.send_message(
                        bot,
                        chat_id,
                        f"{warned_user_mention}, you've been warned {warn_count}/{number_of_reports_to_ban} times. Reason: {reason}",
                        reply_to_message_id=warned_message_id,
                        delete_after=120,
                    )
                    await chat_helper.delete_media_group_messages(bot, chat_id, message.reply_to_message)
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
            if message.from_user.id not in [admin["user_id"] for admin in chat_administrators]:
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

                await chat_helper.delete_media_group_messages(bot, chat_id, message.reply_to_message)

            # Check if the user to ban is an admin of the chat
            for admin in chat_administrators:
                if admin["user_id"] == ban_user_id:
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
            await chat_helper.delete_media_group_messages(bot, chat_id, message.reply_to_message)

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
                manually_verified=True,
                reason_for_action="User was globally banned due to /spam command issued by global admin"
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

        # Delete the command message
        await chat_helper.delete_message(context.bot, chat_id, message.message_id)

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

        # Step 4: Clear all reports for the user across all chats
        reports_cleared = 0
        with db_helper.session_scope() as session:
            # Get all chats where this user has reports
            chat_ids_with_reports = session.query(db_helper.Report.chat_id).filter(
                db_helper.Report.reported_user_id == target_user_id
            ).distinct().all()
            chat_ids_with_reports = [row[0] for row in chat_ids_with_reports]

        # Clear reports in each chat
        for report_chat_id in chat_ids_with_reports:
            success, previous_count = await reporting_helper.clear_reports(
                report_chat_id,
                target_user_id,
                message.from_user.id
            )
            if success and previous_count > 0:
                reports_cleared += previous_count
                logger.info(f"Cleared {previous_count} reports for user {target_user_id} in chat {report_chat_id}")

        target_mention = user_helper.get_user_mention(target_user_id, chat_id)

        # Build status message with reports info
        status_parts = ["unbanned", "unmuted", "message logs updated"]
        if reports_cleared > 0:
            status_parts.append(f"{reports_cleared} reports cleared")
        status_message = ", ".join(status_parts)

        await chat_helper.send_message(
            context.bot,
            chat_id,
            f"User {target_mention} has been unspammed ({status_message}).",
            delete_after=120
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
async def tg_verify_user(update, context):
    """Verify a user to exempt them from spam actions. Super admin only."""
    try:
        message = update.message
        chat_id = update.effective_chat.id

        # Only allow global admin
        if message.from_user.id != int(os.getenv('ENV_BOT_ADMIN_ID')):
            await chat_helper.send_message(
                context.bot, chat_id,
                "You must be a global admin to use this command.",
                reply_to_message_id=message.message_id
            )
            return

        # Parse target user
        target_user_id = user_helper.extract_user_id_from_command(message, message.text.split())
        if not target_user_id:
            await chat_helper.send_message(
                context.bot, chat_id,
                "Usage: /verify_user @username or /verify_user user_id, or reply to a message.",
                reply_to_message_id=message.message_id
            )
            return

        # Delete command message
        await chat_helper.delete_message(context.bot, chat_id, message.message_id)

        # Set verification status
        success = user_helper.set_user_verified(target_user_id, True)

        if success:
            target_mention = user_helper.get_user_mention(target_user_id, chat_id)
            logger.info(f"User {target_user_id} verified by admin {message.from_user.id}")
            await chat_helper.send_message(
                context.bot, chat_id,
                f"User {target_mention} is now verified (exempt from spam actions).",
                delete_after=120
            )
        else:
            await chat_helper.send_message(
                context.bot, chat_id,
                f"User {target_user_id} not found in database.",
                delete_after=60
            )

    except Exception:
        logger.error(f"Error in verify_user: {traceback.format_exc()}")
        await chat_helper.send_message(
            context.bot, chat_id,
            "An error occurred while processing the verify_user command.",
            reply_to_message_id=message.message_id
        )


@sentry_profile()
async def tg_unverify_user(update, context):
    """Remove verification from a user. Super admin only."""
    try:
        message = update.message
        chat_id = update.effective_chat.id

        # Only allow global admin
        if message.from_user.id != int(os.getenv('ENV_BOT_ADMIN_ID')):
            await chat_helper.send_message(
                context.bot, chat_id,
                "You must be a global admin to use this command.",
                reply_to_message_id=message.message_id
            )
            return

        # Parse target user
        target_user_id = user_helper.extract_user_id_from_command(message, message.text.split())
        if not target_user_id:
            await chat_helper.send_message(
                context.bot, chat_id,
                "Usage: /unverify_user @username or /unverify_user user_id, or reply to a message.",
                reply_to_message_id=message.message_id
            )
            return

        # Delete command message
        await chat_helper.delete_message(context.bot, chat_id, message.message_id)

        # Remove verification status
        success = user_helper.set_user_verified(target_user_id, False)

        if success:
            target_mention = user_helper.get_user_mention(target_user_id, chat_id)
            logger.info(f"User {target_user_id} unverified by admin {message.from_user.id}")
            await chat_helper.send_message(
                context.bot, chat_id,
                f"User {target_mention} is no longer verified (spam checks will apply).",
                delete_after=120
            )
        else:
            await chat_helper.send_message(
                context.bot, chat_id,
                f"User {target_user_id} not found in database.",
                delete_after=60
            )

    except Exception:
        logger.error(f"Error in unverify_user: {traceback.format_exc()}")
        await chat_helper.send_message(
            context.bot, chat_id,
            "An error occurred while processing the unverify_user command.",
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
            info_chat_id = os.getenv('ENV_INFO_CHAT_ID')
            error_chat_id = os.getenv('ENV_ERROR_CHAT_ID')

            is_info_chat = False
            if info_chat_id:
                try:
                    is_info_chat = chat_id == int(info_chat_id)
                except ValueError:
                    logger.warning(
                        "ENV_INFO_CHAT_ID is set to a non-integer value. Falling back to default gb ban behaviour."
                    )

            is_error_chat = False
            if error_chat_id:
                try:
                    is_error_chat = chat_id == int(error_chat_id)
                except ValueError:
                    logger.warning(
                        "ENV_ERROR_CHAT_ID is set to a non-integer value. Falling back to default gb ban behaviour."
                    )

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

                # Ban the user directly (no reply message)
                await chat_helper.ban_user(bot, ban_chat_id, ban_user_id, True, reason=ban_reason)

            elif is_info_chat or is_error_chat:
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

            else:  # Check if a user is mentioned in the command message as a reply to message
                if not message.reply_to_message:
                    await message.reply_text("Please reply to a user's message to ban them.")
                    return

                ban_reason = f"User was globally banned by {message.text} command in {await chat_helper.get_chat_mention(bot, chat_id)}. Message: {message.reply_to_message.text}"
                ban_chat_id = chat_id  # We need to ban in the same chat as the command was sent
                ban_user_id = message.reply_to_message.from_user.id

                await chat_helper.delete_media_group_messages(bot, chat_id, message.reply_to_message)

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


@sentry_profile()
async def tg_broadcast_group(update, context):
    """
    Broadcast a message (with optional photo) to all chats in a specific group.
    Usage: /broadcast_group <group_id> <message> or /bg <group_id> <message>
    Can also be used with a photo attachment - the photo will be sent to all chats.
    Only available to bot admin.
    """
    try:
        message = update.message
        chat_id = update.effective_chat.id

        # Check if the command was sent by a global admin of the bot
        if message.from_user.id != int(os.getenv('ENV_BOT_ADMIN_ID')):
            await message.reply_text("You must be a global bot admin to use this command.")
            return

        # Parse command: /bg <group_id> <message>
        command_text = message.text or message.caption or ""
        parts = command_text.split(maxsplit=2)

        if len(parts) < 3:
            await chat_helper.send_message(
                bot, chat_id,
                "Usage: /broadcast_group <group_id> <message>\nExample: /bg 1 Hello everyone!\nYou can also attach a photo.",
                delete_after=10
            )
            return

        try:
            group_id = int(parts[1])
        except ValueError:
            await chat_helper.send_message(
                bot, chat_id,
                f"Invalid group_id: {parts[1]}. Must be an integer.",
                delete_after=10
            )
            return

        broadcast_message = parts[2]

        # Check if there's a photo attached
        photo_file_id = None
        if message.photo:
            # Get the highest resolution photo
            photo_file_id = message.photo[-1].file_id

        # Delete command message only if sent in a group chat, not in private chat with bot
        if update.effective_chat.type in ['group', 'supergroup']:
            try:
                await chat_helper.delete_message(bot, chat_id, message.message_id)
            except:
                pass  # Ignore if deletion fails

        with db_helper.session_scope() as db_session:
            # Get the group and its chats
            chat_group = db_session.query(db_helper.Chat_Group).filter(
                db_helper.Chat_Group.id == group_id
            ).first()

            if not chat_group:
                await chat_helper.send_message(
                    bot, chat_id,
                    f"Group with id {group_id} not found.",
                    delete_after=10
                )
                return

            chats = db_session.query(db_helper.Chat).filter(
                db_helper.Chat.group_id == group_id
            ).all()

            if not chats:
                await chat_helper.send_message(
                    bot, chat_id,
                    f"No chats found in group '{chat_group.name}' (id: {group_id}).",
                    delete_after=10
                )
                return

            # Broadcast to all chats
            success_count = 0
            error_count = 0
            errors = []

            for target_chat in chats:
                try:
                    if photo_file_id:
                        # Send photo with caption
                        await bot.send_photo(
                            chat_id=target_chat.id,
                            photo=photo_file_id,
                            caption=broadcast_message
                        )
                    else:
                        # Send text message only
                        await chat_helper.send_message(bot, target_chat.id, broadcast_message)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(f"Chat {target_chat.id}: {str(e)[:50]}")
                    logger.error(f"Failed to broadcast to chat {target_chat.id}: {traceback.format_exc()}")

            # Report results
            if error_count == 0:
                result_message = f"✅ Broadcast complete! Sent to {success_count}/{len(chats)} chats in group '{chat_group.name}'."
            else:
                result_message = f"⚠️ Broadcast completed with errors: {success_count}/{len(chats)} succeeded, {error_count} failed."
                if errors:
                    result_message += f"\n\nErrors:\n" + "\n".join(errors[:5])
                    if len(errors) > 5:
                        result_message += f"\n... and {len(errors) - 5} more errors"

            await message.reply_text(result_message)

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error in tg_broadcast_group: {traceback.format_exc()} | Update: {update_str}")
        try:
            await update.message.reply_text(f"Error executing broadcast: {str(error)[:200]}")
        except:
            pass


@sentry_profile()
async def tg_broadcast_chat(update, context):
    """
    Broadcast a message (with optional photo) to a specific chat.
    Usage: /broadcast_chat <chat_id> <message> or /bc <chat_id> <message>
    Can also be used with a photo attachment - the photo will be sent to the chat.
    Only available to bot admin.
    """
    try:
        message = update.message
        chat_id = update.effective_chat.id

        # Check if the command was sent by a global admin of the bot
        if message.from_user.id != int(os.getenv('ENV_BOT_ADMIN_ID')):
            await message.reply_text("You must be a global bot admin to use this command.")
            return

        # Parse command: /bc <chat_id> <message>
        command_text = message.text or message.caption or ""
        parts = command_text.split(maxsplit=2)

        if len(parts) < 3:
            await chat_helper.send_message(
                bot, chat_id,
                "Usage: /broadcast_chat <chat_id> <message>\nExample: /bc -1001234567890 Hello everyone!\nYou can also attach a photo.",
                delete_after=10
            )
            return

        try:
            target_chat_id = int(parts[1])
        except ValueError:
            await chat_helper.send_message(
                bot, chat_id,
                f"Invalid chat_id: {parts[1]}. Must be an integer.",
                delete_after=10
            )
            return

        broadcast_message = parts[2]

        # Check if there's a photo attached
        photo_file_id = None
        if message.photo:
            # Get the highest resolution photo
            photo_file_id = message.photo[-1].file_id

        # Delete command message only if sent in a group chat, not in private chat with bot
        if update.effective_chat.type in ['group', 'supergroup']:
            try:
                await chat_helper.delete_message(bot, chat_id, message.message_id)
            except:
                pass  # Ignore if deletion fails

        try:
            if photo_file_id:
                # Send photo with caption
                await bot.send_photo(
                    chat_id=target_chat_id,
                    photo=photo_file_id,
                    caption=broadcast_message
                )
            else:
                # Send text message only
                await chat_helper.send_message(bot, target_chat_id, broadcast_message)

            await message.reply_text(f"✅ Message successfully sent to chat {target_chat_id}.")

        except Exception as e:
            await message.reply_text(f"❌ Failed to send message to chat {target_chat_id}: {str(e)}")
            logger.error(f"Failed to broadcast to chat {target_chat_id}: {traceback.format_exc()}")

    except Exception as error:
        update_str = json.dumps(update.to_dict() if hasattr(update, 'to_dict') else {'info': 'Update object has no to_dict method'}, indent=4, sort_keys=True, default=str)
        logger.error(f"Error in tg_broadcast_chat: {traceback.format_exc()} | Update: {update_str}")
        try:
            await update.message.reply_text(f"Error executing broadcast: {str(error)[:200]}")
        except:
            pass


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
        logger.debug(f"🥶 tg_embeddings_auto_reply called with update: {update}")
        if not (update.message and update.message.text):
            return

        chat_id = update.effective_chat.id
        message_text = update.message.text

        message_embedding = await openai_helper.generate_embedding(message_text)

        logger.debug(f"🥶 tg_embeddings_auto_reply message_embedding: {message_embedding}")

        row = embeddings_reply_helper.find_best_embeddings_trigger(chat_id, message_embedding)

        if not row:
            logger.debug(f"🥶 tg_embeddings_auto_reply no matching row found for chat_id {chat_id} and message_embedding {message_embedding}")
            return
        else:
            logger.info(f"🥶 tg_embeddings_auto_reply found row: {row}")

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
        is_admin = any(admin["user_id"] == message.from_user.id for admin in chat_administrators)
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
            user_nickname = message.from_user.username  # Store only username, NULL if not set
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
            embedding = await openai_helper.generate_embedding(message_content)

            # Process image or video thumbnail if present
            image_description = None
            image_description_embedding = None
            image_file_id = None

            # Get image from photo or video thumbnail
            if message.photo:
                image_file_id = message.photo[-1].file_id
            elif message.video and message.video.thumbnail:
                image_file_id = message.video.thumbnail.file_id

            if image_file_id:
                try:
                    file = await context.bot.get_file(image_file_id)
                    # Get the file URL directly from Telegram
                    image_url = file.file_path

                    # Analyze image with OpenAI Vision
                    image_description = await openai_helper.analyze_image_with_vision(image_url)

                    if image_description:
                        # Generate embedding from the image description
                        image_description_embedding = await openai_helper.generate_embedding(image_description)
                        logger.info(f"Image analyzed and embedded for message {message_id}")
                    else:
                        logger.warning(f"Failed to analyze image for message {message_id}")
                except Exception as e:
                    logger.error(f"Error processing image for message {message_id}: {traceback.format_exc()}")

            # Log the message, treating forwarded messages differently if needed
            # Note: is_spam is intentionally set to None so that spam detection can set it
            # without being overwritten by this function (they run in parallel)
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
                is_spam=None,  # Let spam detection set this value
                embedding=embedding,
                manually_verified=None,  # Let spam detection set this value
                reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None,
                is_forwarded=is_forwarded,
                raw_message=update.message.to_dict() if hasattr(update.message, 'to_dict') else None,
                image_description=image_description,
                image_description_embedding=image_description_embedding
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
        is_admin = any(admin["user_id"] == message.from_user.id for admin in chat_administrators)
        if is_admin:
            return

        # User 777000 is Telegram's service account for channel posts → discussion chats
        # These are legitimate channel posts, not spam
        if message.from_user.id == 777000:
            message_helper.insert_or_update_message_log(
                chat_id=message.chat.id,
                message_id=message.message_id,
                is_spam=False,
                manually_verified=True
            )
            logger.debug(f"Message from user 777000 (channel post) marked as non-spam in chat {message.chat.id}")
            return

        if message.from_user.username == "GroupAnonymousBot":  # Anonymous group admin
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

                            # Log the ban action
                            message_helper.insert_or_update_message_log(
                                chat_id=message.chat.id,
                                message_id=message.message_id,
                                user_id=message.from_user.id,
                                user_nickname=user_helper.get_user_mention(message.from_user.id, message.chat.id),
                                user_current_rating=rating_helper.get_rating(message.from_user.id, message.chat.id),
                                message_content=message.text,
                                action_type="aggressive_antispam_ban",
                                reason_for_action=f"Filtered language ({lang}) detected. Chat: {await chat_helper.get_chat_mention(bot, message.chat.id)}",
                                is_spam=True
                            )

                            logger.info(f"User {user_helper.get_user_mention(message.from_user.id, message.chat.id)} has been banned based on language filter: {lang}")
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

                    # Log the ban action
                    message_helper.insert_or_update_message_log(
                        chat_id=message.chat.id,
                        message_id=message.message_id,
                        user_id=message.from_user.id,
                        user_nickname=user_helper.get_user_mention(message.from_user.id, message.chat.id),
                        user_current_rating=rating_helper.get_rating(message.from_user.id, message.chat.id),
                        message_content=f"APK file: {message.document.file_name}",
                        action_type="aggressive_antispam_ban",
                        reason_for_action=f"APK file uploaded ({message.document.file_name}). Chat: {await chat_helper.get_chat_mention(bot, message.chat.id)}",
                        is_spam=True
                    )

                    logger.info(f"User {user_helper.get_user_mention(message.from_user.id, message.chat.id)} has been banned for uploading an APK file: {message.document.file_name}")
                    return  # exit the function as the user has already been banned

            # Check for story redirects (100% spam)
            if message and message.story:
                # Ban the user for sharing a story redirect
                await chat_helper.delete_message(bot, message.chat.id, message.message_id)
                await chat_helper.ban_user(bot, message.chat.id, message.from_user.id, reason=f"Story redirect shared. Chat: {await chat_helper.get_chat_mention(bot, message.chat.id)}", global_ban=True)

                # Log the ban action
                message_helper.insert_or_update_message_log(
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    user_id=message.from_user.id,
                    user_nickname=user_helper.get_user_mention(message.from_user.id, message.chat.id),
                    user_current_rating=rating_helper.get_rating(message.from_user.id, message.chat.id),
                    message_content=f"Story redirect (story_id: {message.story.id})",
                    action_type="aggressive_antispam_ban",
                    reason_for_action=f"Story redirect shared. Chat: {await chat_helper.get_chat_mention(bot, message.chat.id)}",
                    is_spam=True
                )

                logger.info(f"User {user_helper.get_user_mention(message.from_user.id, message.chat.id)} has been banned for sharing a story redirect (story_id: {message.story.id})")
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
        with sentry_sdk.start_span(op="input_validation", description="Initial checks"):
            message = update.message
            if not message or not message.from_user:
                return

            chat_id = message.chat.id
            user_id = message.from_user.id

            # ───────────── feature-toggle / admin-skip ─────────────
            if chat_helper.get_chat_config(chat_id, "ai_spamcheck_enabled") is not True:
                return
            if any(adm["user_id"] == user_id for adm in await chat_helper.get_chat_administrators(context.bot, chat_id)):
                return
            if user_id == 777000:
                return
            if message.from_user.username == "GroupAnonymousBot":  # Anonymous group admin
                return

        with sentry_sdk.start_span(op="config_and_message", description="Config, thresholds, and message fields"):
            engine     = (chat_helper.get_chat_config(chat_id, "ai_spamcheck_engine") or "legacy").lower()
            engine     = engine if engine in ("legacy", "raw") else "legacy"
            delete_thr = float(chat_helper.get_chat_config(chat_id, "antispam_delete_threshold") or 0.80)
            mute_thr   = float(chat_helper.get_chat_config(chat_id, "antispam_mute_threshold")   or 0.95)

            text      = message.text or message.caption or "Non-text message"
            reply_to  = message.reply_to_message.message_id if message.reply_to_message else None
            forwarded = bool(getattr(message, "forward_from", None) or getattr(message, "forward_from_chat", None))

            # Extract new spam detection features from message
            has_video = bool(getattr(message, "animation", None) or getattr(message, "video", None))
            has_document = bool(getattr(message, "document", None))
            has_photo = bool(getattr(message, "photo", None))
            forwarded_from_channel = (
                getattr(message, "forward_from_chat", None) is not None and
                getattr(message.forward_from_chat, "type", None) == "channel"
            ) if forwarded else False
            # Check for links in entities or caption_entities
            entities = (getattr(message, "entities", None) or []) + (getattr(message, "caption_entities", None) or [])
            has_link = any(e.type in ("url", "text_link") for e in entities) if entities else False
            entity_count = len(entities) if entities else 0

        with sentry_sdk.start_span(op="embedding", description="OpenAI embedding + spam prediction"):
            loop = asyncio.get_event_loop()
            embedding = await openai_helper.generate_embedding(text)

            # Analyze image/video thumbnail if present and generate embedding from description
            image_description_embedding = None
            image_file_id = None

            # Get image from photo or video thumbnail
            if message.photo:
                image_file_id = message.photo[-1].file_id
            elif message.video and message.video.thumbnail:
                image_file_id = message.video.thumbnail.file_id

            if image_file_id:
                try:
                    with sentry_sdk.start_span(op="image_analysis", description="Analyze image with Vision API"):
                        file = await context.bot.get_file(image_file_id)
                        image_url = file.file_path
                        image_description = await openai_helper.analyze_image_with_vision(image_url)
                        if image_description:
                            image_description_embedding = await openai_helper.generate_embedding(image_description)
                            logger.debug(f"Image analyzed for spam check: {image_description[:100]}...")
                except Exception as e:
                    logger.error(f"Error analyzing image for spam check: {traceback.format_exc()}")

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
                    image_description_embedding=image_description_embedding,
                    has_video=has_video,
                    has_document=has_document,
                    has_photo=has_photo,
                    forwarded_from_channel=forwarded_from_channel,
                    has_link=has_link,
                    entity_count=entity_count,
                )

        # Check if user is verified (exempt from spam actions)
        is_verified_user = user_helper.is_user_verified(user_id)

        if is_verified_user:
            # User is verified - log prediction but don't mark as spam or take action
            with sentry_sdk.start_span(op="db_logging_verified", description="DB logging for verified user"):
                message_log_id = message_helper.insert_or_update_message_log(
                    chat_id                     = chat_id,
                    message_id                  = message.message_id,
                    user_id                     = user_id,
                    user_nickname               = message.from_user.username or message.from_user.first_name,
                    user_current_rating         = rating_helper.get_rating(user_id, chat_id),
                    message_content             = text,
                    action_type                 = "spam detection",
                    reporting_id                = context.bot.id,
                    reporting_id_nickname       = "rv_tg_community_bot",
                    reason_for_action           = f"User is manually verified (prediction: {spam_prob:.5f})",
                    is_spam                     = False,
                    manually_verified           = True,
                    spam_prediction_probability = spam_prob,
                    embedding                   = embedding,
                    has_video                   = has_video,
                    has_document                = has_document,
                    has_photo                   = has_photo,
                    forwarded_from_channel      = forwarded_from_channel,
                    has_link                    = has_link,
                    entity_count                = entity_count
                )

            with sentry_sdk.start_span(op="logging_verified", description="Pretty log for verified user"):
                chat_name = await chat_helper.get_chat_mention(context.bot, chat_id)
                user_ment = user_helper.get_user_mention(user_id, chat_id)
                short_txt = (text[:200] + "…") if len(text) > 203 else text

                log_lines = [
                    "",
                    "╔═ AI-Spamcheck (VERIFIED USER)",
                    f"║ Probability  : ✅ {spam_prob:.5f}  (del≥{delete_thr}, mute≥{mute_thr})",
                    f"╚═ 📝 Content   : {short_txt}",
                    f"            ↳ User: {user_ment}",
                    f"            ↳ Chat: {chat_name} ({chat_id})",
                    f"            ↳ Action: verified_bypass (no action taken)",
                    f"            ↳ Engine: {engine}",
                    f"            ↳ Msg-log-ID: {message_log_id}",
                ]
                logger.info("\n".join(log_lines))
            return  # Skip moderation actions for verified users

        with sentry_sdk.start_span(op="db_logging", description="DB logging"):
            message_log_id = message_helper.insert_or_update_message_log(
                chat_id                     = chat_id,
                message_id                  = message.message_id,
                user_id                     = user_id,
                user_nickname               = message.from_user.username or message.from_user.first_name,
                user_current_rating         = rating_helper.get_rating(user_id, chat_id),
                message_content             = text,
                action_type                 = "spam detection",
                reporting_id                = context.bot.id,
                reporting_id_nickname       = "rv_tg_community_bot",
                reason_for_action           = "Automated spam detection",
                is_spam                     = spam_prob >= delete_thr,
                manually_verified           = False,
                spam_prediction_probability = spam_prob,
                embedding                   = embedding,
                has_video                   = has_video,
                has_document                = has_document,
                has_photo                   = has_photo,
                forwarded_from_channel      = forwarded_from_channel,
                has_link                    = has_link,
                entity_count                = entity_count
            )

        with sentry_sdk.start_span(op="moderation_action", description="Moderation actions (delete/mute)"):
            action = "none"
            if spam_prob >= delete_thr:
                with sentry_sdk.start_span(op="moderation_delete", description="Delete message"):
                    await chat_helper.delete_message(context.bot, chat_id, message.message_id)
                action = "delete"

                if spam_prob >= mute_thr:
                    with sentry_sdk.start_span(op="moderation_db_query", description="Query user status chats"):
                        with db_helper.session_scope() as session:
                            rows = session.query(db_helper.User_Status.chat_id) \
                                        .filter_by(user_id=user_id) \
                                        .all()
                        chat_ids = [cid for (cid,) in rows]

                    if not chat_ids:
                        with sentry_sdk.start_span(op="moderation_db_query_msglog", description="Query message log chats"):
                            with db_helper.session_scope() as session:
                                rows = session.query(db_helper.Message_Log.chat_id) \
                                            .filter(db_helper.Message_Log.user_id == user_id) \
                                            .distinct() \
                                            .all()
                            chat_ids = [cid for (cid,) in rows]

                    try:
                        with sentry_sdk.start_span(op="moderation_mute", description="Mute user"):
                            await chat_helper.mute_user(
                                context.bot, chat_id, user_id,
                                duration_in_seconds=21*24*60*60,
                                global_mute=True, reason="AI spam detection"
                            )
                    except Exception as e:
                        logger.error(f"global_mute failed for {user_id}: {e}")

                    action = "delete+mute"

        with sentry_sdk.start_span(op="logging", description="Pretty log"):
            chat_name = await chat_helper.get_chat_mention(context.bot, chat_id)
            user_ment = user_helper.get_user_mention(user_id, chat_id)
            short_txt = (text[:200] + "…") if len(text) > 203 else text
            vis_emoji = "‼️" if action=="delete+mute" else "⚠️" if action=="delete" else "👌"

            log_lines = [
                "",
                "╔═ AI-Spamcheck",
                f"║ Probability  : {vis_emoji} {spam_prob:.5f}  (del≥{delete_thr}, mute≥{mute_thr})",
                f"╚═ 📝 Content   : {short_txt}",
                f"            ↳ User: {user_ment}",
                f"            ↳ Chat: {chat_name} ({chat_id})",
                f"            ↳ Action: {action}",
                f"            ↳ Engine: {engine}",
                f"            ↳ Msg-log-ID: {message_log_id}",
                f"            ↳ Fwd/Reply: forwarded={forwarded} reply_to={reply_to}",
                f"            ↳ raw_message={message.to_dict() if hasattr(message, 'to_dict') else None}",
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

BRIGHTDATA_PROXY = os.getenv("BRIGHTDATA_PROXY")

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

CAS_CACHE_OK_SECONDS = 5        # 5 secfor users not banned
CAS_CACHE_BANNED_SECONDS = 3000   # 3000 sec for banned users (to allow fast unmute etc)
CAS_CACHE_FAILED_SECONDS = 1   # 10 sec if API fails

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
            checks.append((member.id, 0, member.username))  # Store only username, NULL if not set
    else:
        msg = update.message
        checks.append((msg.from_user.id, msg.message_id, msg.from_user.username))  # Store only username, NULL if not set

    MAX_RETRIES = 3
    RETRY_DELAY = 1  # seconds

    async with aiohttp.ClientSession() as session:
        for user_id, message_id, nickname in checks:
            admins = await chat_helper.get_chat_administrators(context.bot, chat_id)
            if any(a["user_id"] == user_id for a in admins):
                continue

            if nickname == "GroupAnonymousBot":  # Anonymous group admin
                continue

            # --- cache logic here ---
            cache_key = f"cas_status:{user_id}"
            cached = cache_helper.get_key(cache_key)
            if cached is not None:
                # Possible values: "ok", "banned", "not_found", "api_fail"
                if cached == "ok":
                    logger.info(f"CAS cache: user {user_id} is ok, skipping API check.")
                    continue
                if cached == "not_found":
                    logger.info(f"CAS cache: user {user_id} not found in CAS, skipping API check.")
                    continue
                if cached == "banned":
                    logger.info(f"CAS cache: user {user_id} previously banned, acting immediately.")
                    # No continue: repeat the action below
                if cached == "api_fail":
                    logger.info(f"CAS cache: recent API fail for user {user_id}, skipping for now.")
                    continue

            # If not cached (or was "banned"), check API
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
                cache_helper.set_key(cache_key, "api_fail", CAS_CACHE_FAILED_SECONDS)
                continue

            data = await resp.json()
            desc = data.get("description", "")

            if not data.get("ok", False):
                if "Record not found" in desc:
                    cache_helper.set_key(cache_key, "not_found", CAS_CACHE_OK_SECONDS)
                    logger.info(f"CAS API no record for user {user_id}")
                else:
                    cache_helper.set_key(cache_key, "api_fail", CAS_CACHE_FAILED_SECONDS)
                    logger.info(f"CAS API not ok for user {user_id}: {desc}")
                continue

            if data.get("result", False):
                cache_helper.set_key(cache_key, "banned", CAS_CACHE_BANNED_SECONDS)
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
            else:
                cache_helper.set_key(cache_key, "ok", CAS_CACHE_OK_SECONDS)

@sentry_profile()
async def tg_thankyou_message(update, context):
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
                                username=target.username  # NULL if not set
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
                                username=reactor.username  # NULL if not set
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
        logger.error(f"Error in tg_thankyou_message: {traceback.format_exc()} | Update: {update_str}")


@sentry_profile()
async def tg_thankyou_reaction(update, context):
    """Handle message reactions for rating changes."""
    try:
        reaction_update = update.message_reaction
        if not reaction_update:
            return

        # Skip anonymous reactions
        reactor_user = reaction_update.user
        if reactor_user is None:
            return

        chat_id = reaction_update.chat.id
        message_id = reaction_update.message_id
        reactor_user_id = reactor_user.id

        # Detect newly added reactions
        old_emojis = set(extract_emoji_list(reaction_update.old_reaction))
        new_emojis = set(extract_emoji_list(reaction_update.new_reaction))
        newly_added = new_emojis - old_emojis

        if not newly_added:
            return  # No new reactions added

        # Get reaction config
        like_reactions = chat_helper.get_chat_config(chat_id, "like_reactions") or []
        dislike_reactions = chat_helper.get_chat_config(chat_id, "dislike_reactions") or []

        # Determine rating change
        rating_change = None
        for emoji in newly_added:
            if emoji in like_reactions:
                rating_change = +1
                break
            elif emoji in dislike_reactions:
                rating_change = -1
                break

        if rating_change is None:
            return  # No matching reaction

        # Get message author from database
        with db_helper.session_scope() as db_session:
            message_log = db_session.query(db_helper.Message_Log).filter(
                db_helper.Message_Log.message_id == message_id,
                db_helper.Message_Log.chat_id == chat_id
            ).first()

            if not message_log or not message_log.user_id:
                return  # Message not found or no author

            message_author_id = message_log.user_id

            # Skip self-reactions
            if reactor_user_id == message_author_id:
                logger.info(f"Self-reaction ignored: user {reactor_user_id}")
                return

            # Ensure both users exist in DB (same pattern as tg_thankyou)
            author = db_session.query(db_helper.User).get(message_author_id)
            if author is None:
                author = db_helper.User(
                    id=message_author_id,
                    first_name="Unknown",
                    last_name="",
                    username=None
                )
                db_session.add(author)

            reactor = db_session.query(db_helper.User).get(reactor_user_id)
            if reactor is None:
                reactor = db_helper.User(
                    id=reactor_user_id,
                    first_name=reactor_user.first_name or "",
                    last_name=reactor_user.last_name or "",
                    username=reactor_user.username
                )
                db_session.add(reactor)

        # Apply rating change (same signature as tg_thankyou)
        await rating_helper.change_rating(
            message_author_id,      # user receiving rating
            reactor_user_id,        # judge giving rating
            chat_id,
            rating_change,          # +1 or -1
            message_id,
            delete_message_delay=5*60
        )

        logger.info(f"Reaction rating: user {reactor_user_id} -> {message_author_id} ({rating_change:+d})")

    except Exception as error:
        update_str = json.dumps(update.to_dict(), indent=2) if hasattr(update, 'to_dict') else "{}"
        logger.error(f"Error in tg_thankyou_reaction: {traceback.format_exc()} | Update: {update_str}")


@sentry_profile()
async def tg_set_rating(update, context):
    try:
        chat_id = update.effective_chat.id
        message = update.message or update.edited_message

        if not message:
            return

        # Check if the user is an administrator
        chat_administrators = await chat_helper.get_chat_administrators(context.bot, chat_id)
        is_admin = any(admin["user_id"] == message.from_user.id for admin in chat_administrators)
        if not is_admin:
            await chat_helper.send_message(context.bot, chat_id, "You must be an admin to use this command.", reply_to_message_id=message.message_id, delete_after=120)
            return

        # Delete the command message
        await chat_helper.delete_message(context.bot, chat_id, message.message_id)

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
            await chat_helper.send_message(context.bot, chat_id, f"Rating for user ID {target_user_id} is already set to {new_rating}.", delete_after=120)

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
    logger.debug(f"Update type: {type(update)} -- {update.to_dict()}")

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
                
        
        welcome_message_template = chat_helper.get_chat_config(update.effective_chat.id, "welcome_message")

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

            # Send personalized welcome message if configured
            if welcome_message_template:
                # Replace {{user_mention}} placeholder with simplified user mention (name + username only)
                if "{{user_mention}}" in welcome_message_template:
                    user_mention = user_helper.get_user_mention(
                        new_user_id,
                        update.effective_chat.id,
                        show_user_id=False,
                        show_account_age=False,
                        show_rating=False
                    )
                    personalized_message = welcome_message_template.replace("{{user_mention}}", user_mention)
                else:
                    personalized_message = welcome_message_template

                await chat_helper.send_message(bot, update.effective_chat.id, personalized_message, disable_web_page_preview=True)

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
                        # Get author name from sender_chat (the channel/user they're posting as)
                        author_name = update.message.sender_chat.title or update.message.sender_chat.username or update.message.sender_chat.first_name or "Unknown"
                        reposted_text = f"{author_name}: {update.message.text}"

                        await chat_helper.delete_message(bot, update.message.chat.id, update.message.message_id)
                        # Preserve reply relationship if the original message was a reply (keeps message in comments section)
                        reply_to_id = update.message.reply_to_message.message_id if update.message.reply_to_message else None
                        await chat_helper.send_message(bot, update.message.chat.id, reposted_text, reply_to_message_id=reply_to_id)
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
            self.application.run_polling(allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post", "message_reaction", "message_reaction_count", "inline_query", "chosen_inline_result", "callback_query", "shipping_query", "pre_checkout_query", "poll", "poll_answer", "my_chat_member", "chat_member", "chat_join_request"])
        except Exception as e:
            if "Event loop is closed" in str(e):
                logger.info("Received shutdown signal, exiting gracefully")
            else:
                logger.error(f"Error: {traceback.format_exc()}")


import threading
from aiohttp import web

def start_health_server():
    async def handle(request):
        return web.Response(text="OK")
    app = web.Application()
    app.router.add_get("/healthz", handle)
    runner = web.AppRunner(app)
    async def run():
        await runner.setup()
        port = int(os.getenv("PORT", 8080))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
    loop = asyncio.get_event_loop()
    loop.create_task(run())

# temporary heartbeat function to check if the bot is alive
# TODO:MED: remove this function later
@sentry_profile()
async def tg_heartbeat(context):
    logger.debug("💓 heartbeat")

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
    start_health_server()

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
    # application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION), tg_thankyou_message), group=3)
    application.add_handler(CommandHandler(["report", "r"], tg_report, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["warn", "w"], tg_warn, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["offtop", "o"], tg_offtop, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["set_rating", "sr"], tg_set_rating, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["set_report"], tg_set_report, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["ur", "unreport"], tg_ur, filters.ChatType.GROUPS), group=4)
    application.add_handler(CommandHandler(["get_rating", "gr"], tg_get_rating, filters.ChatType.GROUPS), group=4)
    application.add_handler(ChatJoinRequestHandler(tg_join_request), group=5)
    application.add_handler(CommandHandler(["ban", "b"], tg_ban, filters.ChatType.GROUPS), group=6)
    application.add_handler(CommandHandler(["gban", "g", "gb"], tg_gban), group=6)
    application.add_handler(CommandHandler(["spam", "s"], tg_spam), group=6)
    application.add_handler(CommandHandler(["unspam", "us"], tg_unspam), group=6)
    application.add_handler(CommandHandler(["verify_user", "vu"], tg_verify_user), group=6)
    application.add_handler(CommandHandler(["unverify_user", "uvu"], tg_unverify_user), group=6)
    # Broadcast handlers support both text commands and commands with photos (captions)
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^/(broadcast_group|bg)\s'),
        tg_broadcast_group
    ), group=6)
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r'^/(broadcast_group|bg)\s'),
        tg_broadcast_group
    ), group=6)
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^/(broadcast_chat|bc)\s'),
        tg_broadcast_chat
    ), group=6)
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.CaptionRegex(r'^/(broadcast_chat|bc)\s'),
        tg_broadcast_chat
    ), group=6)
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
    application.add_handler(
        MessageReactionHandler(tg_thankyou_reaction),
        group=8
    )
    application.add_handler(CommandHandler(["pin", "p"], tg_pin, filters.ChatType.GROUPS), group=9)
    application.add_handler(CommandHandler(["unpin", "up"], tg_unpin, filters.ChatType.GROUPS), group=9)
    application.add_handler(CommandHandler(["help", "h"], tg_help), group=10)
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.ChatType.GROUPS, trigger_action_helper.execute_chains_for_message), group=11)
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION), tg_auto_reply), group=12)
    application.add_handler(CommandHandler(["info", "i"], tg_info), group=13)
    application.add_handler(CommandHandler(["ping", "p"], tg_ping), group=14)
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION), tg_embeddings_auto_reply), group=15)

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
            self.application.run_polling(allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post", "message_reaction", "message_reaction_count", "inline_query", "chosen_inline_result", "callback_query", "shipping_query", "pre_checkout_query", "poll", "poll_answer", "my_chat_member", "chat_member", "chat_join_request"])
        except Exception as e:
            if "Event loop is closed" in str(e):
                logger.info("Received shutdown signal, exiting gracefully")
            else:
                logger.error(f"Error: {traceback.format_exc()}")

if __name__ == "__main__":
    manager = BotManager()
    manager.run()
