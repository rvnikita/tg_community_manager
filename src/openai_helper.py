from openai import AsyncOpenAI
import psycopg2
import psycopg2.extras
import configparser
import traceback
import asyncio
import openai

import src.logging_helper as logging_helper
import src.config_helper as config_helper



config = config_helper.get_config()

logger = logging_helper.get_logger()

client = AsyncOpenAI(api_key = config['OPENAI']['KEY'])


async def chat_completion_create(messages, model="gpt-3.5-turbo"):
    """
    Asynchronously sends a request to OpenAI's API to create chat completions,
    using a specified model for chat-based interactions.

    Args:
    - messages (list): A list of dictionaries defining the messages for chat interaction,
                       each with 'role' and 'content' keys.
    - model (str): The model to use for the completion.

    Returns:
    - The response from the OpenAI API.
    """
    try:
        chat_completion = await client.chat.completions.create(
            messages=messages,
            model=model,
        )
        return chat_completion
    except Exception as e:
        logger.error(f"Error creating chat completion with OpenAI: {traceback.format_exc()}")
        return None

def generate_embedding(text):
    response = openai.Embedding.create(
        engine=config['OPENAI']['EMBEDDING_MODEL'],
        input=text
    )

    return response

def get_nearest_vectors(query, threshold = config['OPENAI']['SIMILARITY_THRESHOLD']):
    embedding = generate_embedding(query)

    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])

        #select row and distance from qna where cosine similarity is greater than 0.9 and return top 5
        sql = f"SELECT *, (1 - (embedding <-> '{embedding.data[0].embedding}')::float) AS similarity FROM tg_qna WHERE (1 - (embedding <-> '{embedding.data[0].embedding}')::float) > {threshold} ORDER BY similarity DESC LIMIT 5"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)

        rows = cur.fetchall()

        return rows


    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Error: {traceback.format_exc()}")
    finally:
        if conn is not None:
            conn.close()
