import openai
import os
import configparser
from admin_log import admin_log

import psycopg2
import psycopg2.extras

config = configparser.ConfigParser()
config_path = os.path.dirname(__file__) + '/../config/' #we need this trick to get path to config folder
config.read(config_path + 'openai.ini')
config.read(config_path + 'db.ini')

openai.api_key = config['OPENAI']['KEY']

def generate_embedding(text):
    response = openai.Embedding.create(
        engine=config['OPENAI']['EMBEDDING_MODEL'],
        input=text
    )

    return response

def get_nearest_vectors(query):
    embedding = generate_embedding(query)

    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])

        #select row and distance from qna where cosine similarity is greater than 0.9 and return top 5
        sql = f"SELECT *, (1 - (embedding <-> '{embedding.data[0].embedding}')::float) AS similarity FROM qna WHERE (1 - (embedding <-> '{embedding.data[0].embedding}')::float) > {config['OPENAI']['SIMILARITY_THRESHOLD']} ORDER BY similarity DESC LIMIT 5"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        return rows


    except (Exception, psycopg2.DatabaseError) as error:
        admin_log(f"Error in file {__file__}: {error}", critical=True)
    finally:
        if conn is not None:
            conn.close()
