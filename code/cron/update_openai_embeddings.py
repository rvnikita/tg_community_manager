import sys
sys.path.insert(0, '../') # add parent directory to the path
from admin_log import admin_log
import openai_helper

import openai
import os
import configparser
import psycopg2.extras

from datetime import datetime
import psycopg2

config = configparser.ConfigParser()
config_path = os.path.dirname(os.path.dirname(__file__)) + '/../config/' #we need this trick to get path to config folder
config.read(config_path + 'openai.ini')
config.read(config_path + 'db.ini')

openai.api_key = config['OPENAI']['KEY']

# function that select all messages from database without embedding, generate them and write them back to database
def update_embeddings():
    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])

        #sql select all rows from qna table without embedding
        sql = "SELECT * FROM qna WHERE embedding IS NULL"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        #generate embeddings for all messages
        for row in rows:
            embedding = openai_helper.generate_embedding(row['title'] + row['body'])
            #write embedding to database
            sql = f"UPDATE qna SET embedding = '{embedding.data[0].embedding}' WHERE id = {row['id']}"
            cur.execute(sql)
            conn.commit()
            admin_log(f"Embedding for message {row['id']} generated", critical=True)

    except (Exception, psycopg2.DatabaseError) as error:
        admin_log(f"Error while connecting to PostgreSQL: {error}", critical=True)
    finally:
        if conn is not None:
                conn.close()

if __name__ == '__main__':
    update_embeddings()