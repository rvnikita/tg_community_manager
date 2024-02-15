import openai
import src.logging_helper as logging_helper
import src.config_helper as config_helper

import psycopg2
import psycopg2.extras
import configparser
import traceback
import asyncio

config = config_helper.get_config()

logger = logging_helper.get_logger()

openai.api_key = config['OPENAI']['KEY']


async def chat_completion_create(messages, engine=None):
    """
    Asynchronously sends a request to OpenAI's API to create chat completions,
    using a specified or default engine for chat-based models.

    Args:
    - messages (list): A list of messages for chat interaction, each as a dict with 'role' and 'content'.
    - engine (str, optional): The engine to use for the completion. Defaults to configuration if not specified.

    Returns:
    - OpenAI API response object.
    """
    if engine is None:
        engine = config['OPENAI']['DEFAULT_ENGINE']

    # Ensure correct types for other parameters
    default_temperature = float(config['OPENAI']['DEFAULT_TEMPERATURE'])
    default_max_tokens = int(config['OPENAI']['DEFAULT_MAX_TOKENS'])

    try:
        # Construct the messages payload correctly for the chat API
        prompt = {
            "model": engine,
            "messages": messages,
            "temperature": default_temperature,
            "max_tokens": default_max_tokens,
        }

        # Use asyncio to run the synchronous OpenAI API call in an executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: openai.ChatCompletion.create(**prompt))

        return response
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
