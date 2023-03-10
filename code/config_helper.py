from admin_log import admin_log
import db_helper

import psycopg2
import configparser
import os
import json

def get_config(chat_id = None):
    try:
        #TODO: may be we should store config value in global variable and not call db every time?
        #TODO: add default values + check if config does not exit save default values to db

        conn = db_helper.connect()
        cur = conn.cursor()

        sql = f"SELECT * FROM config WHERE chat_id = {chat_id}"
        cur.execute(sql)
        config = cur.fetchone()

        if config is not None:
            return config['config_value']
        else:
            #here we should create default config and paste in into db
            #default value is stored in config table under chat_id = 0 row
            sql = f"SELECT * FROM config WHERE chat_id = 0"
            cur.execute(sql)
            default_config = cur.fetchone()

            if default_config is not None:
                sql = f"INSERT INTO config (chat_id, config_value) VALUES ({chat_id}, '{json.dumps(default_config['config_value'])}')"
                cur.execute(sql)
                conn.commit()
                return default_config['config_value']

            return None


    except Exception as e:
        admin_log(f"Error in {__file__}: {e}", critical=True)
        return None




