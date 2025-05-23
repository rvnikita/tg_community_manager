import sys
sys.path.insert(0, '../') # add parent directory to the path
import openai
import psycopg2.extras
import traceback
import os
from datetime import datetime
import psycopg2

import src.logging_helper as logging_helper
import src.openai_helper as openai_helper


logger = logging_helper.get_logger()

openai.api_key = os.getenv('ENV_OPENAI_KEY')

# function that select all messages from database without embedding, generate them and write them back to database
def update_embeddings():
    conn = None
    try:
        conn = psycopg2.connect(user=os.getenv('ENV_DB_USER'),
                                password=os.getenv('ENV_DB_PASSWORD'),
                                host=os.getenv('ENV_DB_HOST'),
                                port=os.getenv('ENV_DB_PORT'),
                                database=os.getenv('ENV_DB_NAME'))

        #sql select all rows from qna table without embedding
        sql = "SELECT * FROM tg_qna WHERE embedding IS NULL"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        #generate embeddings for all messages
        for row in rows:
            embedding = openai_helper.generate_embedding(row['title'])
            #write embedding to database
            sql = f"UPDATE tg_qna SET embedding = '{embedding.data[0].embedding}' WHERE id = {row['id']}"
            cur.execute(sql)
            conn.commit()
            logging_helper.info(f"Embedding for message {row['id']} generated")

    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Error: {traceback.format_exc()}")
    finally:
        if conn is not None:
                conn.close()

if __name__ == '__main__':
    update_embeddings()