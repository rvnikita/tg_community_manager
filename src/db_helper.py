from admin_log import admin_log
import config_helper

import psycopg2
import psycopg2.extras
import os
import inspect #we need this to get current file name path

config = config_helper.get_config()

def connect():
    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'], cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    except (Exception, psycopg2.DatabaseError) as error:
        #write admin log mentioning file name and error
        admin_log(f"Error in {__file__}: while connecting to PostgreSQL: {error}", critical=True)

        return None