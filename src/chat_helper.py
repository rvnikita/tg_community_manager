from src.admin_log import admin_log
import src.db_helper as db_helper

import psycopg2
import configparser
import os
import json
from telegram import ChatPermissions
from datetime import datetime, timedelta

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
            admin_log(f"Error in {__file__}: {e}", critical=True)
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
            admin_log(f"Error in {__file__}: {e}", critical=True)
            return None


async def warn_user(bot, chat_id: int, user_id: int) -> None:
    # bot.send_message(chat_id, text=f"User {user_id} has been warned due to multiple reports.")
    pass

async def mute_user(bot, chat_id: int, user_id: int) -> None:
    permissions = ChatPermissions(can_send_messages=False)
    await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=datetime.now() + timedelta(hours=24))

async def ban_user(bot, chat_id: int, user_id: int) -> None:
    await bot.kick_chat_member(chat_id, user_id)

async def delete_message(bot, chat_id: int, message_id: int) -> None:
    await bot.delete_message(chat_id, message_id)