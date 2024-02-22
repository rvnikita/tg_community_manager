import src.logging_helper as logging
import src.db_helper as db_helper
import src.chat_helper as chat_helper
import src.cache_helper as cache_helper


import psycopg2
import configparser
import os
import json
import asyncio

from sqlalchemy.orm.exc import NoResultFound

from telegram import ChatPermissions
from telegram.error import BadRequest, TelegramError
from datetime import datetime, timedelta
import traceback
import re

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
                # Logic for handling chat configuration when chat_id is not found in the database
                return default  # Return the default value when chat_id is not found
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





async def send_message(bot, chat_id, text, reply_to_message_id = None, delete_after = None, disable_web_page_preview = True):
    """
    Send a message and optionally delete it after a specified delay.

    :param bot: Bot instance.
    :param chat_id: Chat ID where the message will be sent.
    :param text: Text of the message to be sent.
    :param reply_to_message_id: ID of the message to which the new message will reply.
    :param delete_after: Duration (in seconds) after which the sent message will be deleted. If None, the message will not be deleted.
    """
    message = await bot.send_message(chat_id=chat_id, text=text, reply_to_message_id=reply_to_message_id, disable_web_page_preview=disable_web_page_preview)

    if delete_after is not None:
        asyncio.create_task(delete_message(bot, chat_id, message.message_id, delay_seconds=delete_after))


async def warn_user(bot, chat_id: int, user_id: int) -> None:
    # bot.send_message(chat_id, text=f"User {user_id} has been warned due to multiple reports.")
    pass

async def mute_user(bot, chat_id: int, user_id: int) -> None:
    permissions = ChatPermissions(can_send_messages=False)
    await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=datetime.now() + timedelta(hours=24))

from db_helper import session_scope

async def ban_user(bot, chat_id, user_to_ban, global_ban=False, reason=None):
    with session_scope() as db_session:
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

async def schedule_message_deletion(chat_id, user_id, message_id, reply_to_message_id=None, delay_hours=2):
    try:
        with db_helper.session_scope() as db_session:
            from datetime import datetime, timedelta

            scheduled_deletion_time = datetime.utcnow() + timedelta(hours=delay_hours)
            new_deletion = db_helper.Message_Deletion(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                reply_to_message_id=reply_to_message_id,
                status='scheduled',
                scheduled_deletion_time=scheduled_deletion_time
            )
            db_session.add(new_deletion)
            db_session.commit()
            logger.info(f"Scheduled message {message_id} for deletion at {scheduled_deletion_time}")
            return True
    except Exception as e:
        logger.error(f"Error scheduling message {message_id} for deletion: {traceback.format_exc()}")
        return False


async def delete_scheduled_messages(bot, chat_id=None, user_id=None, message_id=None):
    """
    Delete scheduled messages based on given criteria.

    :param bot: Bot instance to perform message deletions.
    :param chat_id: Chat ID from where messages should be deleted (can be None).
    :param user_id: User ID whose messages should be deleted (can be None).
    :param message_id: Specific message ID to delete (can be None).
    """
    try:
        with db_helper.session_scope() as db_session:
            # Build the query based on provided criteria
            query = db_session.query(db_helper.Message_Deletion).filter(db_helper.Message_Deletion.status == 'scheduled')

            if chat_id is not None:
                query = query.filter(db_helper.Message_Deletion.chat_id == chat_id)
            if user_id is not None:
                query = query.filter(db_helper.Message_Deletion.user_id == user_id)
            if message_id is not None:
                query = query.filter(db_helper.Message_Deletion.message_id == message_id)

            # Execute the query
            messages = query.all()

            for message in messages:
                try:
                    await bot.delete_message(message.chat_id, message.message_id)
                    message.status = 'deleted'  # Update the status to 'deleted' after successful deletion
                    logger.info(f"Deleted scheduled message {message.message_id} in chat {message.chat_id} for user {message.user_id}")
                except Exception as e:
                    logger.error(f"Failed to delete scheduled message {message.message_id} in chat {message.chat_id} for user {message.user_id}: {e}")

            db_session.commit()
            return True
    except Exception as e:
        logger.error(f"Error deleting scheduled messages based on criteria: {traceback.format_exc()}")
        return False


async def schedule_message_deletion(chat_id, user_id, message_id, reply_to_message_id=None, delay_seconds=None):
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
                reply_to_message_id=reply_to_message_id,
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

