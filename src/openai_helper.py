import openai
import src.logging_helper as logging_helper
import src.config_helper as config_helper

import psycopg2
import psycopg2.extras
import configparser
import traceback

config = config_helper.get_config()

logger = logging_helper.get_logger()

openai.api_key = config['OPENAI']['KEY']


async def chat_completions_create(messages, model = None):
    """
    Sends a request to OpenAI's Chat Completion API with a series of chat messages,
    using a specified or default model.

    Args:
    - messages (list of dict): A list of message dictionaries for chat interaction,
                               each with 'role' and 'content' keys.
    - model (str, optional): The model to use for the chat completion. If not specified,
                             the default model from the configuration is used.

    Returns:
    - OpenAI API response object.
    """

    try:
        if model is None:
            model = config['OPENAI']['DEFAULT_MODEL']

        response = openai.ChatCompletion.create(model=model, messages=messages)
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
