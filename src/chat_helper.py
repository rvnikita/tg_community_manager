import src.logging_helper as logging
import src.db_helper as db_helper
import src.chat_helper as chat_helper

import psycopg2
import configparser
import os
import json

from sqlalchemy.orm.exc import NoResultFound

from telegram import ChatPermissions
from telegram.error import BadRequest
from datetime import datetime, timedelta
import traceback

logger = logging.get_logger()

def get_default_chat(config_param=None):
    with db_helper.session_scope() as db_session:
        try:
            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == 0).one_or_none()

            if chat is not None:
                if config_param is not None:
                    if config_param in chat.config:
                        return chat.config[config_param]
                    else:
                        return None
                else:
                    return chat.config
            else:
                return None
        except Exception as e:
            logger.error(f"Error: {traceback.format_exc()}")
            return None

def get_chat_config(chat_id=None, config_param=None):
    with db_helper.session_scope() as db_session:
        try:
            chat = db_session.query(db_helper.Chat).filter(db_helper.Chat.id == chat_id).one_or_none()

            if chat is not None:
                if config_param is not None:
                    if config_param in chat.config:
                        return chat.config[config_param]
                    else:
                        default_config_param_value = get_default_chat(config_param)
                        if default_config_param_value is not None:
                            chat.config[config_param] = default_config_param_value
                            db_session.commit()
                            return default_config_param_value
                else:
                    return chat.config
            else:
                default_full_config = get_default_chat()
                if default_full_config is not None:
                    new_chat = db_helper.Chat(id=chat_id, config=default_full_config)
                    db_session.add(new_chat)
                    db_session.commit()

                if config_param is not None:
                    default_config = get_default_chat(config_param)
                    if default_config is not None:
                        return default_config
                    else:
                        return None
                else:
                    return default_full_config
        except Exception as e:
            logger.error(f"Error: {traceback.format_exc()}")
            return None


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
            await bot.ban_chat_member(chat_id, user_to_ban)

            if global_ban:
                logger.info(f"User {user_to_ban} has been globally banned. Reason: {reason}")
                # If global_ban is True, ban the user in all chats
                all_chats = db_session.query(db_helper.Chat.id).filter(db_helper.Chat.id != 0).all()
                bot_info = await bot.get_me()

                for chat in all_chats:
                    try:
                        #check if bot is admin
                        logger.info(f"Trying to get admins of chat {chat.id}")
                        chat_admins = await bot.get_chat_administrators(chat.id)
                        logger.info(f"Get admins of chat {chat.id}")

                        logger.info("Checking if bot is admin in chat")
                        if bot_info.id not in [admin.user.id for admin in chat_admins]:
                            logger.info("Bot is not admin in chat")
                            continue
                        else:
                            logger.info("Bot is admin in chat")
                            logger.info(f"Trying to ban user {user_to_ban} from chat {chat.id}")
                            await bot.ban_chat_member(chat.id, user_to_ban)
                    except BadRequest:
                        logger.error(f"Error: Bot is not an admin or chat does not exist. Chat: {chat_helper.get_chat_mention(bot, chat.id)}")
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
            else:
                logger.info(f"User {user_to_ban} has been banned in chat {await chat_helper.get_chat_mention(bot, chat_id)}. Reason: {reason}")

            # The commit is handled by the context manager
        except Exception as e:
            logger.error(f"Error: {traceback.format_exc()}")
            return None


async def delete_message(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")


async def get_chat_mention(bot, chat_id: int) -> str:
    try:
        # Fetch chat details from the Telegram API
        chat_details = await bot.get_chat(chat_id)
    except BadRequest as e:
        # Handle case if bot has not enough rights to get chat details
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

