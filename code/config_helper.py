from admin_log import admin_log
import db_helper

import psycopg2
import configparser
import os
import json

def get_config(chat_id = None):
    try:
        #TODO: may be we should store config value in global variable and not call db every time?

        conn = db_helper.connect()
        cur = conn.cursor()

        sql = f"SELECT * FROM config WHERE chat_id = {chat_id}"
        cur.execute(sql)
        config = cur.fetchone()

        if config is not None:
            return config['config_value']
        else:
            return None


    except Exception as e:
        admin_log(f"Error in {__file__}: {e}", critical=True)
        return None




