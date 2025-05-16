import psycopg2
import configparser
import os
import json
import asyncio
import pytz

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import func, or_, text
import sqlalchemy as sa


from telegram import ChatPermissions
from telegram.error import BadRequest, TelegramError
from datetime import datetime, timedelta, timezone
import traceback
import re

import src.logging_helper as logging
import src.db_helper as db_helper
import src.chat_helper as chat_helper
import src.cache_helper as cache_helper


logger = logging.get_logger()

async def send_message_to_admin(bot, chat_id, text: str, disable_web_page_preview: bool = True):
    chat_administrators = await bot.get_chat_administrators(chat_id)

    for admin in chat_administrators:
        if admin.user.is_bot == True: #don't send to bots
            continue
        try:
            await chat_helper.send_message(bot, admin.user.id, text, disable_web_page_preview = True)
        except TelegramError as error:
            if error.message == "Forbidden: bot was blocked by the user":
                logger.info(f"Bot was blocked by the user {admin.user.id}.")
            elif error.message == "Forbidden: user is deactivated":
                logger.info(f"User {admin.user.id} is deactivated.")
            elif error.message == "Forbidden: bot can't initiate conversation with a user":
                logger.info(f"Bot can't initiate conversation with a user {admin.user.id}.")
            else:
                logger.error(f"Telegram error: {error.message}. Traceback: {traceback.format_exc()}")
        except Exception as error:
            logger.error(f"Error: {traceback.format_exc()}")

def get_default_chat(config_param=None):
    cache_key = f"default_chat_config:{config_param}"
    config_value = cache_helper.get_key(cache_key)

    if config_value:
        return json.loads(config_value)  # Deserialize JSON string back into Python object

    with db_helper.session_scope() as db_session:
        try:
            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == 0).one_or_none()

            if chat is not None:
                if config_param is not None:
                    if config_param in chat.config:
                        cache_helper.set_key(cache_key, json.dumps(chat.config[config_param]), expire=86400)  # Cache result
                        return chat.config[config_param]
                    else:
                        return None
                else:
                    cache_helper.set_key(cache_key, json.dumps(chat.config), expire=3600)  # Cache entire config
                    return chat.config
            else:
                return None
        except Exception as e:
            logger.error(f"Error: {traceback.format_exc()}")
            return None

def get_chat_config(chat_id=None, config_param=None, default=None):
    
    # skip DM chats
    if chat_id > 0:
        return default

    cache_key = f"chat_config:{chat_id}:{config_param}"
    config_value = cache_helper.get_key(cache_key)

    if config_value:
        return json.loads(config_value)  # Deserialize JSON string back into Python object

    with db_helper.session_scope() as db_session:
        try:
            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat_id).one_or_none()

            if chat is not None:
                if config_param is not None:
                    if config_param in chat.config:
                        cache_helper.set_key(cache_key, json.dumps(chat.config[config_param]), expire=3600)  # Cache result
                        return chat.config[config_param]
                    else:
                        default_config_param_value = get_default_chat(config_param)
                        if default_config_param_value is not None:
                            chat.config[config_param] = default_config_param_value
                            db_session.commit()
                            cache_helper.set_key(cache_key, json.dumps(default_config_param_value), expire=3600)  # Cache result
                            return default_config_param_value
                else:
                    cache_helper.set_key(cache_key, json.dumps(chat.config), expire=3600)  # Cache entire config
                    return chat.config
            else:
                # If chat_id is not found, handle accordingly without attempting to access attributes of None
                default_config_param_value = get_default_chat(config_param)
                if default_config_param_value is not None:
                    logger.info(f"Default config param {config_param} value: {default_config_param_value} for chat_id {chat_id}")
                    # Let's insert the chat into the database but with empty config
                    db_session.add(db_helper.Chat(id=chat_id, config={}))

                    return default_config_param_value
                else:
                    return default  # Return the default value in case of any error
        except Exception as e:
            logger.error(f"Error: {traceback.format_exc()}")
            return default  # Return the default value in case of any error

async def get_last_admin_permissions_check(chat_id):
    try:
        with db_helper.session_scope() as db_session:
            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat_id).one_or_none()
            if chat and chat.last_admin_permission_check:
                return chat.last_admin_permission_check
    except Exception as error:
        logger.error(f"Error retrieving last admin permissions check for chat_id {chat_id}: {traceback.format_exc()}")
    return None

async def set_last_admin_permissions_check(chat_id, timestamp):
    try:
        with db_helper.session_scope() as db_session:
            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat_id).one_or_none()
            if chat:
                chat.last_admin_permission_check = timestamp
                db_session.commit()  # Assuming commit can be awaited
                return True
            else:
                logger.error(f"Chat {chat_id} not found for updating last admin permissions check.")
                return False
    except Exception as e:
        logger.error(f"Error updating last admin permissions check for chat_id {chat_id}: {traceback.format_exc()}")
        return False

async def send_message(
    bot,
    chat_id,
    text,
    reply_to_message_id=None,
    delete_after=None,
    disable_web_page_preview=True,
    parse_mode=None
):
    message = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_to_message_id=reply_to_message_id,
        disable_web_page_preview=disable_web_page_preview,
        parse_mode=parse_mode
    )

    if delete_after is not None:
        asyncio.create_task(delete_message(bot, chat_id, message.message_id, delay_seconds=delete_after))

    return message



async def send_scheduled_messages(bot):
    try:
        with db_helper.session_scope() as db_session:
            now = datetime.now(pytz.utc)
            current_day_of_week = now.weekday()  # Monday is 0 and Sunday is 6
            current_day_of_month = now.day
            current_time = now.time()

            # Construct the due condition
            due_condition = or_(
                db_helper.Scheduled_Message_Config.last_sent == None,
                db_helper.Scheduled_Message_Config.last_sent + db_helper.Scheduled_Message_Config.frequency_seconds * text("INTERVAL '1 second'") <= now
            )

            potential_messages_to_send = db_session.query(db_helper.Scheduled_Message_Config).join(
                db_helper.Scheduled_Message_Content
            ).filter(
                db_helper.Scheduled_Message_Config.status == 'active',
                or_(
                    db_helper.Scheduled_Message_Config.time_of_the_day == None,
                    db_helper.Scheduled_Message_Config.time_of_the_day <= current_time
                ),
                or_(
                    db_helper.Scheduled_Message_Config.day_of_the_week == None,
                    db_helper.Scheduled_Message_Config.day_of_the_week == current_day_of_week
                ),
                or_(
                    db_helper.Scheduled_Message_Config.day_of_the_month == None,
                    db_helper.Scheduled_Message_Config.day_of_the_month == current_day_of_month
                ),
                due_condition
            ).all()

            logger.info(f"Found {len(potential_messages_to_send)} messages due to be sent.")

            for scheduled_config in potential_messages_to_send:
                message_content = scheduled_config.message_content.content
                parse_mode = scheduled_config.message_content.parse_mode

                logger.info(f"Sending message ID {scheduled_config.id}: {message_content[:50]}...")

                try:
                    await send_message(
                        bot,
                        scheduled_config.chat_id,
                        message_content,
                        parse_mode=parse_mode
                    )
                    scheduled_config.last_sent = now
                    scheduled_config.error_count = 0
                    scheduled_config.error_message = None
                except Exception as e:
                    logger.error(f"Error sending scheduled message ID {scheduled_config.id}: {traceback.format_exc()}")
                    scheduled_config.error_count += 1
                    scheduled_config.error_message = str(e)
                    ERROR_THRESHOLD = 3
                    if scheduled_config.error_count >= ERROR_THRESHOLD:
                        scheduled_config.status = 'error'
                        logger.error(f"Scheduled message ID {scheduled_config.id} set to 'error' status after {ERROR_THRESHOLD} failures.")

            db_session.commit()

    except Exception as error:
        logger.error(f"Error while fetching and sending scheduled messages: {traceback.format_exc()}")



async def warn_user(bot, chat_id: int, user_id: int) -> None:
    # bot.send_message(chat_id, text=f"User {user_id} has been warned due to multiple reports.")
    pass

async def mute_user(bot, chat_id: int, user_id: int, duration_in_hours: float = None) -> None:
    # build a ChatPermissions that denies literally everything
    perms = ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False
    )

    if duration_in_hours is not None:
        until = datetime.now(timezone.utc) + timedelta(hours=duration_in_hours)
        desc = f"for {duration_in_hours:.2f}h (until {until.isoformat()})"
    else:
        # indefinite
        until = None
        desc = "indefinitely"

    logger.info(f"mute_user: restricting user={user_id} in chat={chat_id} {desc}")
    try:
        # pass the until_date kwarg explicitly
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=perms,
            until_date=until
        )
        logger.info(f"mute_user: SUCCESS user={user_id} in chat={chat_id}")
    except TelegramError as e:
        logger.error(f"mute_user: TELEGRAM ERROR muting user={user_id} in chat={chat_id}: {e.message}")
    except Exception as e:
        logger.error(f"mute_user: UNEXPECTED ERROR muting user={user_id} in chat={chat_id}: {traceback.format_exc()}")


async def unmute_user(bot, chat_id, user_to_unmute, global_unmute=False):
    """
    Unmute a user by restoring full chat permissions.
    If global_unmute is True, the user is unmuted in all chats.
    """
    # Define default full permissions using all individual media parameters.
    default_perms = ChatPermissions(
        can_send_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True
    )
    try:
        # Determine the list of chat IDs to process.
        with db_helper.session_scope() as session:
            if global_unmute:
                all_chats = session.query(db_helper.Chat.id).filter(db_helper.Chat.id != 0).all()
                chat_ids = [chat.id for chat in all_chats]
            else:
                chat_ids = [chat_id]
        # For each chat, try to restore permissions (i.e. unmute).
        for cid in chat_ids:
            try:
                await bot.restrict_chat_member(cid, user_to_unmute, permissions=default_perms)
                # logger.info(f"User {user_to_unmute} unmuted (permissions restored) in chat {cid}")
            except BadRequest as e:
                if e.message == "Method is available only for supergroups":
                    continue
                elif e.message == "Chat not found":
                    continue
                else:
                    logger.error(f"BadRequest in chat {cid} during unmute: {e.message}")
            except TelegramError as e:
                if e.message == "Forbidden: bot is not a member of the group chat":
                    continue
                if e.message == "Forbidden: bot was kicked from the group chat":
                    continue
                if e.message == "Forbidden: user is deactivated":
                    continue
                else:
                    logger.error(f"Telegram error in chat {cid} during unban: {e.message}")
            except Exception as e:
                logger.error(f"Unexpected error during unmute in chat {cid}: {e}. Traceback: {traceback.format_exc()}")
    except Exception as e:
        logger.error(f"General error in unmute_user function: {e}. Traceback: {traceback.format_exc()}")



async def ban_user(bot, chat_id, user_to_ban, global_ban=False, reason=None):
    with db_helper.session_scope() as db_session:
        try:
            if chat_id is not None:
                try:
                    await bot.ban_chat_member(chat_id, user_to_ban)
                except BadRequest:
                    logger.error(
                        f"BadRequest. Chat: {await chat_helper.get_chat_mention(bot, chat_id)}. Traceback: {traceback.format_exc()}")
                except Exception as e:
                    logger.error(f"Error: {traceback.format_exc()}")

            if global_ban:
                # If global_ban is True, ban the user in all chats
                all_chats = db_session.query(db_helper.Chat.id).filter(db_helper.Chat.id != 0).all()
                bot_info = await bot.get_me()

                for chat in all_chats:
                    try:
                        #check if bot is admin
                        #logger.info(f"Trying to get admins of chat {chat.id}")
                        chat_admins = await bot.get_chat_administrators(chat.id)
                        #logger.info(f"Get admins of chat {chat.id}")

                        #logger.info("Checking if bot is admin in chat")
                        if bot_info.id not in [admin.user.id for admin in chat_admins]:
                            logger.info(f"Bot is not admin in chat {await chat_helper.get_chat_mention(bot, chat.id)}")
                            continue
                        else:
                            #logger.info("Bot is admin in chat")
                            #logger.info(f"Trying to ban user {user_to_ban} from chat {chat.id}")
                            await bot.ban_chat_member(chat.id, user_to_ban)
                    except TelegramError as e:
                        if "Bot is not a member of the group chat" in e.message:
                            logger.info(f"Bot is not a member in chat {await chat_helper.get_chat_mention(bot, chat.id)}")
                            continue
                        elif "Group migrated to supergroup. New chat id" in e.message:
                            # Extract new chat id from the exception message using a regular expression
                            new_chat_id = int(re.search(r"New chat id: (-\d+)", e.message).group(1))

                            # Check if new chat id already exists in the database
                            existing_chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == new_chat_id).first()
                            if existing_chat:
                                # Handle the case where the new chat id already exists
                                logger.info(f"Cannot update chat id from {await chat_helper.get_chat_mention(bot, chat.id)} to {await chat_helper.get_chat_mention(bot, new_chat_id)} as the new id already exists")
                            else:
                                # Update the chat id as before
                                chat_to_update = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat.id).first()
                                if chat_to_update:
                                    chat_to_update.id = new_chat_id
                                    db_session.commit()
                                    logger.info(f"Updated chat id from {chat.id} to {new_chat_id}")
                                else:
                                    logger.error(f"Could not find chat with id {chat.id} to update")
                        elif "bot was kicked from the supergroup chat" in e.message:
                            logger.info(f"Bot was kicked from chat {await chat_helper.get_chat_mention(bot, chat.id)}")
                            continue


                    except BadRequest as e:
                        if "There are no administrators in the private chat" in e.message:
                            logger.info(f"Bot is not admin in chat {await chat_helper.get_chat_mention(bot, chat.id)}")
                            continue
                        elif "User_not_participant" in e.message:
                            logger.info(f"User {user_to_ban} is not in chat {chat.id}")
                            continue
                        logger.error(f"BadRequest. Chat: {await chat_helper.get_chat_mention(bot, chat.id)}. Traceback: {traceback.format_exc()}")
                        continue
                    except Exception as e:
                        if e.message == "Chat not found":
                            continue
                        else:
                            logger.error(f"Error: {traceback.format_exc()}")
                            continue

                #check if user is already in User_Global_Ban table
                banned_user = db_session.query(db_helper.User_Global_Ban).filter(db_helper.User_Global_Ban.user_id == user_to_ban).one_or_none()

                if banned_user is None:
                    # Add user to User_Global_Ban table
                    banned_user = db_helper.User_Global_Ban(
                        user_id = user_to_ban,
                        reason = reason,
                    )
                    db_session.add(banned_user)

                logger.info(f"User {user_to_ban} has been globally banned. Reason: {reason}")
            else:
                logger.info(f"User {user_to_ban} has been banned in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {reason}")

            # The commit is handled by the context manager
        except Exception as e:
            logger.error(f"Error: {traceback.format_exc()}")
            return None

async def unban_user(bot, chat_id, user_to_unban, global_unban=False):
    """
    Unban a user from a chat or, if global_unban is True, from all chats in the database.
    """
    try:
        # Determine the list of chat IDs to process.
        with db_helper.session_scope() as session:
            if global_unban:
                all_chats = session.query(db_helper.Chat.id).filter(db_helper.Chat.id != 0).all()
                chat_ids = [chat.id for chat in all_chats]
            else:
                chat_ids = [chat_id]

        # For each chat, try to unban the user.
        for cid in chat_ids:
            try:
                await bot.unban_chat_member(cid, user_to_unban)
                # logger.info(f"User {user_to_unban} unbanned from chat {cid}")
            except BadRequest as e:
                if e.message == "Method is available only for supergroups":
                    continue
                if e.message == "Method is available for supergroup and channel chats only":
                    continue
                elif e.message == "Chat not found":
                    continue
                else:
                    logger.error(f"BadRequest in chat {cid} during unban: {e.message}")
            except TelegramError as e:
                if e.message == "Forbidden: bot is not a member of the group chat":
                    continue
                if e.message == "Forbidden: bot was kicked from the group chat":
                    continue
                if e.message == "Forbidden: user is deactivated":
                    continue
                else:
                    logger.error(f"Telegram error in chat {cid} during unban: {e.message}")
            except Exception as e:
                logger.error(f"Unexpected error during unban in chat {cid}: {e}. Traceback: {traceback.format_exc()}")
    except Exception as e:
        logger.error(f"General error in unban_user function: {e}. Traceback: {traceback.format_exc()}")



async def delete_message(bot, chat_id: int, message_id: int, delay_seconds: int = None) -> None:
    if delay_seconds:
        await asyncio.sleep(delay_seconds)

    try:
        await bot.delete_message(chat_id, message_id)
    except BadRequest as e:
        if "Message to delete not found" in str(e):
            logger.info(f"Message with ID {message_id} in chat {chat_id} not found or already deleted.")
        else:
            logger.error(f"BadRequest Error: {e}. Traceback: {traceback.format_exc()}")
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")

async def schedule_message_deletion(chat_id, user_id, message_id, trigger_id=None, delay_seconds=None):
    try:
        with db_helper.session_scope() as db_session:
            from datetime import datetime, timedelta

            scheduled_deletion_time = datetime.utcnow() + timedelta(seconds=delay_seconds) if delay_seconds is not None else None
            new_deletion = db_helper.Message_Deletion(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                status='scheduled',
                scheduled_deletion_time=scheduled_deletion_time,
                trigger_id=trigger_id  # Link the message to a specific event or trigger
            )
            db_session.add(new_deletion)
            db_session.commit()
            logger.info(f"Message {message_id} scheduled for deletion with trigger ID {trigger_id}" if trigger_id else f"Message {message_id} scheduled for deletion without specific trigger")
            return True
    except Exception as e:
        logger.error(f"Error scheduling message {message_id} for deletion: {traceback.format_exc()}")
        return False


async def delete_scheduled_messages(bot, chat_id=None, trigger_id=None, user_id=None, message_id=None):
    try:
        with db_helper.session_scope() as db_session:
            query = db_session.query(db_helper.Message_Deletion).filter(db_helper.Message_Deletion.status == 'scheduled')

            # Apply filters based on provided criteria
            if chat_id:
                query = query.filter(db_helper.Message_Deletion.chat_id == chat_id)
            if user_id:
                query = query.filter(db_helper.Message_Deletion.user_id == user_id)
            if message_id:
                query = query.filter(db_helper.Message_Deletion.message_id == message_id)
            if trigger_id:
                query = query.filter(db_helper.Message_Deletion.trigger_id == trigger_id)

            messages = query.all()
            for message in messages:
                try:
                    await bot.delete_message(message.chat_id, message.message_id)
                    message.status = 'deleted'
                    logger.info(f"Deleted message {message.message_id} for trigger ID {trigger_id}")
                except Exception as e:
                    logger.error(f"Failed to delete message {message.message_id} for trigger ID {trigger_id}: {e}")

            db_session.commit()
            return True
    except Exception as e:
        logger.error(f"Error deleting messages for trigger ID {trigger_id}: {traceback.format_exc()}")
        return False


async def schedule_message_deletion(chat_id, message_id, user_id = None, trigger_id = None, delay_seconds=None):
    """
    Schedule a message for deletion.

    :param chat_id: Chat ID where the message exists.
    :param user_id: User ID who sent the message.
    :param message_id: ID of the message to be scheduled for deletion.
    :param reply_to_message_id: ID of the message that this message is replying to.
    :param delay_seconds: Seconds after which the message should be deleted. If None, no automatic deletion time is set.
    """
    try:
        with db_helper.session_scope() as db_session:
            from datetime import datetime, timedelta

            scheduled_deletion_time = datetime.utcnow() + timedelta(seconds=delay_seconds) if delay_seconds is not None else None
            new_deletion = db_helper.Message_Deletion(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                trigger_id = trigger_id,
                status='scheduled',
                scheduled_deletion_time=scheduled_deletion_time
            )
            db_session.add(new_deletion)
            db_session.commit()
            logger.info(f"Scheduled message {message_id} for deletion at {scheduled_deletion_time}" if delay_seconds is not None else f"Message {message_id} scheduled for deletion without a specific time")
            return True
    except Exception as e:
        logger.error(f"Error scheduling message {message_id} for deletion: {traceback.format_exc()}")
        return False

async def pin_message(bot, chat_id, message_id):
    try:
        await bot.pin_chat_message(chat_id, message_id)
    except BadRequest as e:
        if "message to pin not found" in e.message:
            logger.info(f"Message with ID {message_id} in chat {chat_id} not found or already deleted.")
        else:
            logger.error(f"BadRequest Error: {e}. Traceback: {traceback.format_exc()}")
    except Exception as e:
        logger.error(f"Error pinning message {message_id} in chat {chat_id}: {traceback.format_exc()}")

async def unpin_message(bot, chat_id, message_id):
    try:
        await bot.unpin_chat_message(chat_id, message_id)
    except BadRequest as e:
        if "message to unpin not found" in e.message:
            logger.info(f"Message to unpin not found in chat {chat_id}")
        else:
            logger.error(f"BadRequest Error: {e}. Traceback: {traceback.format_exc()}")
    except Exception as e:
        logger.error(f"Error unpinning messages in chat {chat_id}: {traceback.format_exc()}")



async def get_chat_mention(bot, chat_id: int) -> str:
    try:
        # Fetch chat details from the Telegram API
        chat_details = await bot.get_chat(chat_id)
    except BadRequest as e:
        # Handle case if bot has not enough rights to get chat details
        return str(chat_id)
    except TelegramError as e:
        return str(chat_id)
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        return str(chat_id)

    with db_helper.session_scope() as db_session:
        try:
            # Try to get the chat from the database
            chat = db_session.query(db_helper.Chat).filter_by(id=chat_id).one()

            # Update the chat name and invite link
            chat.chat_name = chat_details.title
            chat.invite_link = chat_details.invite_link  # Store invite link in invite_link field

            db_session.commit()

            # Create chat mention
            chat_mention = chat.chat_name if chat.chat_name else str(chat.id)
            invite_link = chat.invite_link if chat.invite_link else "No link available"

            return f"{chat_mention} - {invite_link}"

        except NoResultFound:
            # If chat is not found in the database, create a new one
            chat = db_helper.Chat(
                id=chat_id,
                chat_name=chat_details.title,
                invite_link=chat_details.invite_link,  # Store invite link in invite_link field
            )
            db_session.add(chat)
            db_session.commit()

            return f"{chat.chat_name} - {chat.invite_link}"


async def get_auto_replies(chat_id, filter_delayed=False):
    """
    Fetch auto-reply settings for a specific chat, optionally filtering out replies that are currently delayed.
    """
    try:
        cache_key = f"auto_replies:{chat_id}:{filter_delayed}"
        auto_replies = cache_helper.get_key(cache_key)

        if auto_replies:
            return json.loads(auto_replies)  # Deserialize JSON string back into Python object

        with db_helper.session_scope() as db_session:
            if filter_delayed:
                current_time = datetime.now(timezone.utc)
                auto_replies = db_session.query(db_helper.Auto_Reply).filter(db_helper.Auto_Reply.chat_id == chat_id, or_(db_helper.Auto_Reply.last_reply_time == None, func.extract('epoch', func.now() - db_helper.Auto_Reply.last_reply_time) > db_helper.Auto_Reply.reply_delay)).all()
            else:
                auto_replies = db_session.query(db_helper.Auto_Reply).filter(
                    db_helper.Auto_Reply.chat_id == chat_id
                ).all()

            auto_replies_list = [{'id': ar.id, 'trigger': ar.trigger, 'reply': ar.reply, 'reply_delay': ar.reply_delay, 'last_reply_time': ar.last_reply_time.isoformat() if ar.last_reply_time else None} for ar in auto_replies]
            cache_helper.set_key(cache_key, json.dumps(auto_replies_list), expire=3600)
            return auto_replies_list
    except Exception as e:
        logger.error(f"Error fetching auto replies for chat_id {chat_id}: {traceback.format_exc()}")
        return []

async def update_last_reply_time_and_increment_count(chat_id, auto_reply_id, new_time):
    try:
        with db_helper.session_scope() as db_session:
            auto_reply = db_session.query(db_helper.Auto_Reply).filter(
                db_helper.Auto_Reply.chat_id == chat_id,
                db_helper.Auto_Reply.id == auto_reply_id
            ).one_or_none()

            if auto_reply:
                auto_reply.last_reply_time = new_time
                if auto_reply.usage_count is None:
                    auto_reply.usage_count = 1  # Initialize it if it's null
                else:
                    auto_reply.usage_count += 1  # Otherwise, increment it
                db_session.commit()
                cache_helper.delete_key(f"auto_replies:{chat_id}:True")
                cache_helper.delete_key(f"auto_replies:{chat_id}:False")
                return True
    except Exception as e:
        logger.error(f"Error updating last reply time for chat_id {chat_id}, auto_reply_id {auto_reply_id}, and incrementing usage count: {traceback.format_exc()}")
        return False
