from openai import AsyncOpenAI, OpenAI
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

# For asynchronous API calls
async_client = AsyncOpenAI(api_key=config['OPENAI']['KEY'])

# For synchronous API calls
client = OpenAI(api_key=config['OPENAI']['KEY'])


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
        chat_completion = await async_client.chat.completions.create(
            messages=messages,
            model=model,
        )
        return chat_completion
    except Exception as e:
        logger.error(f"Error creating chat completion with OpenAI: {traceback.format_exc()}")
        return None

import requests
import traceback

from src.config_helper import get_config
from src.db_helper import session_scope, Message_Log
from src.logging_helper import get_logger

# Configure logger
logger = get_logger()

# Load configuration
config = get_config()
OPENAI_API_KEY = config['OPENAI']['KEY']
OPENAI_MODEL = config['OPENAI']['EMBEDDING_MODEL']

def generate_embedding(text):
    """Call OpenAI API to get embeddings for the given text."""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_KEY}'
    }
    response = requests.post(
        'https://api.openai.com/v1/embeddings',
        headers=headers,
        json={
            'input': text,
            'model': OPENAI_MODEL
        }
    )
    response_json = response.json()
    if 'data' in response_json and len(response_json['data']) > 0:
        return response_json['data'][0]['embedding']
    else:
        logger.error(f"Failed to retrieve embedding: {response_json.get('error', 'No error information available')}")
        return None

def update_embeddings():
    """Update embeddings for messages without embeddings and non-empty content."""
    try:
        with session_scope() as session:
            # Retrieve all messages without embeddings and with non-null and non-empty message content
            messages = session.query(Message_Log).filter(
                Message_Log.embedding == None,
                Message_Log.message_content != None,
                Message_Log.message_content != ''
            ).all()

            for message in messages:
                logger.info(f"Processing message ID: {message.id}")
                # Ensure the message content is not just whitespace
                if not message.message_content.strip():
                    logger.info(f"Skipping message ID: {message.id} due to empty content.")
                    continue

                # Retrieve embedding if not already present
                embedding = get_openai_embedding(message.message_content)
                if embedding:
                    message.embedding = embedding
                    session.commit()
                    logger.info(f"Updated embedding for Message ID: {message.id}")
                else:
                    logger.error(f"Failed to update embedding for Message ID: {message.id}")
    except Exception as e:
        logger.error(f"An error occurred while updating embeddings: {e}. Traceback: {traceback.format_exc()}")


if __name__ == '__main__':
    update_embeddings()


def get_nearest_vectors(query, threshold=config['OPENAI']['SIMILARITY_THRESHOLD']):
    """
    Retrieves vectors nearest to the given query based on a cosine similarity threshold.

    Args:
    - query (str): The text query to be embedded and compared.
    - threshold (float): The cosine similarity threshold for vector comparison.

    Returns:
    - A list of database rows corresponding to similar vectors.
    """
    embedding = generate_embedding(query)
    if embedding is None:
        logger.error("Failed to generate embedding for nearest vector search.")
        return []

    conn = None
    try:
        conn = psycopg2.connect(user=config['DB']['DB_USER'],
                                password=config['DB']['DB_PASSWORD'],
                                host=config['DB']['DB_HOST'],
                                port=config['DB']['DB_PORT'],
                                database=config['DB']['DB_DATABASE'])

        sql = f"""SELECT *, (1 - (embedding <-> '{embedding}')::float) AS similarity
                  FROM tg_qna
                  WHERE (1 - (embedding <-> '{embedding}')::float) > {threshold}
                  ORDER BY similarity DESC LIMIT 5"""
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)
        rows = cur.fetchall()

        return rows
    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Database error: {traceback.format_exc()}")
        return []
    finally:
        if conn:
            conn.close()
