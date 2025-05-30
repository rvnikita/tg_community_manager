from openai import AsyncOpenAI, OpenAI
import psycopg2
import psycopg2.extras
import configparser
import traceback
import asyncio
import os

import src.helpers.logging_helper as logging_helper
from src.helpers.db_helper import session_scope, Message_Log

logger = logging_helper.get_logger()

# For asynchronous API calls
async_client = AsyncOpenAI(api_key=os.getenv('ENV_OPENAI_KEY'))

# For synchronous API calls (if needed elsewhere)
client = OpenAI(api_key=os.getenv('ENV_OPENAI_KEY'))

OPENAI_MODEL = os.getenv('ENV_OPENAI_EMBEDDING_MODEL')

async def chat_completion_create(messages, model="gpt-3.5-turbo"):
    """
    Asynchronously sends a request to OpenAI's API to create chat completions,
    using a specified model for chat-based interactions.
    Args:
        messages (list): [{'role': ..., 'content': ...}, ...]
        model (str): Model name.
    Returns:
        The response from the OpenAI API.
    """
    try:
        chat_completion = await async_client.chat.completions.create(
            messages=messages,
            model=model,
        )
        return chat_completion
    except Exception:
        logger.error(f"Error creating chat completion with OpenAI: {traceback.format_exc()}")
        return None

async def generate_embedding(text):
    """
    Asynchronously get embeddings for the given text using OpenAI.
    Args:
        text (str): Text to embed.
    Returns:
        list[float] or None: The embedding, or None on failure.
    """
    try:
        response = await async_client.embeddings.create(
            input=text,
            model=OPENAI_MODEL
        )
        return response.data[0].embedding
    except Exception:
        logger.error(f"Failed to retrieve embedding: {traceback.format_exc()}")
        return None

async def update_embeddings():
    """
    Asynchronously update embeddings for messages without embeddings and non-empty content.
    """
    try:
        with session_scope() as session:
            messages = session.query(Message_Log).filter(
                Message_Log.embedding == None,
                Message_Log.message_content != None,
                Message_Log.message_content != ''
            ).all()

            for message in messages:
                logger.info(f"Processing message ID: {message.id}")
                if not message.message_content.strip():
                    logger.info(f"Skipping message ID: {message.id} due to empty content.")
                    continue

                embedding = await generate_embedding(message.message_content)
                if embedding:
                    message.embedding = embedding
                    session.commit()
                    logger.info(f"Updated embedding for Message ID: {message.id}")
                else:
                    logger.error(f"Failed to update embedding for Message ID: {message.id}")
    except Exception as e:
        logger.error(f"An error occurred while updating embeddings: {e}. Traceback: {traceback.format_exc()}")

if __name__ == '__main__':
    asyncio.run(update_embeddings())
