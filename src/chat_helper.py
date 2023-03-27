from src.admin_log import admin_log
import src.db_helper as db_helper

import psycopg2
import configparser
import os
import json

def get_default_chat(config_param=None):
    try:
        chat = db_helper.session.query(db_helper.Chat).filter(db_helper.Chat.id == 0).one_or_none()

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

def get_chat(chat_id=None, config_param=None):
    try:
        chat = db_helper.session.query(db_helper.Chat).filter(db_helper.Chat.id == id).one_or_none()

        if chat is not None:
            if config_param is not None:
                if config_param in chat.config:
                    return chat.config[config_param]
                else:
                    default_config_param_value = get_default_chat(config_param)
                    if default_config_param_value is not None:
                        chat.config[config_param] = default_config_param_value
                        db_helper.session.commit()
                        return default_config_param_value
            else:
                return chat.config
        else:
            default_full_config = get_default_chat()
            if default_full_config is not None:
                new_chat = db_helper.Chat(id=chat_id, config=default_full_config)
                db_helper.session.add(new_chat)
                db_helper.session.commit()

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
    finally:
        db_helper.session.close()




