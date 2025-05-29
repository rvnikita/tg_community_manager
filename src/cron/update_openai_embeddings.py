import sys
sys.path.insert(0, '../') # add parent directory to the path
import openai
import psycopg2.extras
import traceback
import os
from datetime import datetime
import psycopg2
import asyncio

import src.helpers.logging_helper as logging_helper
import src.helpers.openai_helper as openai_helper


logger = logging_helper.get_logger()

openai.api_key = os.getenv('ENV_OPENAI_KEY')

# function that select all messages from database without embedding, generate them and write them back to database
async def update_embeddings():
    conn = None
    try:
        conn = psycopg2.connect(user=os.getenv('ENV_DB_USER'),
                                password=os.getenv('ENV_DB_PASSWORD'),
                                host=os.getenv('ENV_DB_HOST'),
                                port=os.getenv('ENV_DB_PORT'),
                                database=os.getenv('ENV_DB_NAME'))

        sql = "SELECT * FROM tg_qna WHERE embedding IS NULL"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)
        rows = cur.fetchall()

        for row in rows:
            embedding = await openai_helper.generate_embedding(row['title'])
            if embedding:
                # Store as string/array, depending on your schema. Adjust as needed:
                sql_update = "UPDATE tg_qna SET embedding = %s WHERE id = %s"
                cur.execute(sql_update, (embedding, row['id']))
                conn.commit()
                logger.info(f"Embedding for message {row['id']} generated")
            else:
                logger.error(f"Failed to generate embedding for message {row['id']}")
    except Exception:
        logger.error(f"Error: {traceback.format_exc()}")
    finally:
        if conn is not None:
            conn.close()

if __name__ == '__main__':
    asyncio.run(update_embeddings())