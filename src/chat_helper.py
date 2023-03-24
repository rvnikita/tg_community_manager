from src.admin_log import admin_log
import src.db_helper as db_helper

import psycopg2
import configparser
import os
import json

def get_default_chat(config_param = None):
    try:
        conn = db_helper.connect()
        cur = conn.cursor()

        sql = f"SELECT * FROM chat WHERE chat_id = 0"
        cur.execute(sql)
        chat_row = cur.fetchone()

        if chat_row is not None: #we have info in DB
            #check if config_param is not None, then we need to return only one value, elsewise return all config
            if config_param is not None:
                if config_param in chat_row['config_value']:
                    return chat_row['config_value'][config_param] #return only specific value
                else:
                    return None
            else:
                return chat_row['config_value'] #return all config from JSON
        else:
            return None

    except Exception as e:
        admin_log(f"Error in {__file__}: {e}", critical=True)
        return None

def get_chat(chat_id = None, config_param = None):
    try:
        #TODO: may be we should store config value in global variable and not call db every time?
        #TODO: add default values + check if config does not exit save default values to db

        conn = db_helper.connect()
        cur = conn.cursor()

        sql = f"SELECT * FROM chat WHERE chat_id = {chat_id}"
        cur.execute(sql)
        config_row = cur.fetchone()

        if config_row is not None: #we have info in DB
            #check if config_param is not None, then we need to return only one value, elsewise return all config
            if config_param is not None:

                #check if config_param in config_row['config_value'] if not we need to update config adding value from default config
                if config_param in config_row['config_value']:
                    return config_row['config_value'][config_param] #return only specific value
                else: #we don't have config_param in config_row['config_value'] so we need to update config with default value
                    default_config_param_value = get_default_chat(config_param)
                    if default_config_param_value is not None:
                        config_row['config_value'][config_param] = default_config_param_value
                        sql = f"UPDATE chat SET config_value = '{json.dumps(config_row['config_value'])}' WHERE chat_id = {chat_id}"
                        cur.execute(sql)
                        conn.commit()
                        return default_config_param_value
            else:
                return config_row['config_value'] #return all config from JSON
        else: #we don't have info in DB so we return default config and create new row in DB
            #here we should create default config and paste in into db
            #default value is stored in config table under chat_id = 0 row


            default_full_config = get_default_chat()
            if default_full_config is not None: #we have default config
                sql = f"INSERT INTO config (chat_id, config_value, chat_name) VALUES ({chat_id}, '{json.dumps(default_full_config)}', NULL)"
                cur.execute(sql)
                conn.commit()

            if config_param is not None:
                default_config = get_default_chat(config_param)
                if default_config is not None:
                    return default_config
                else: #we don't have config_param in default config
                    return None
            else:
                return default_full_config


    except Exception as e:
        admin_log(f"Error in {__file__}: {e}", critical=True)
        return None




