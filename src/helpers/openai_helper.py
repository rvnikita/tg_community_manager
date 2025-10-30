from openai import AsyncOpenAI, OpenAI
import psycopg2
import psycopg2.extras
import configparser
import traceback
import asyncio
import os
import json

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

async def analyze_image_with_vision(image_url):
    """
    Asynchronously analyze an image using OpenAI Vision API.
    Args:
        image_url (str): URL or base64 data URI of the image to analyze.
    Returns:
        str or None: The image description, or None on failure.
    """
    try:
        response = await async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in detail, focusing on any text, objects, and context that might be relevant for spam detection."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception:
        logger.error(f"Failed to analyze image with vision: {traceback.format_exc()}")
        return None

async def call_openai_structured(prompt: str, response_format: dict, model: str = "gpt-4o-mini"):
    """
    Call OpenAI with structured output using JSON schema.

    This function is used for trigger-action chains and other features that need
    structured, validated responses from the LLM.

    Args:
        prompt (str): The prompt to send to the LLM
        response_format (dict): JSON schema defining expected output structure
        model (str): Model to use (must support structured output). Default: gpt-4o-mini

    Returns:
        dict or None: Parsed JSON response as dict, or None on error

    Example:
        schema = {
            "type": "object",
            "properties": {
                "matches": {"type": "boolean"},
                "reason": {"type": "string"}
            },
            "required": ["matches", "reason"]
        }
        result = await call_openai_structured("Is this spam?", schema)
        # Returns: {"matches": true, "reason": "Contains promotional content"}
    """
    try:
        response = await async_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "response_schema",
                    "schema": response_format,
                    "strict": True
                }
            }
        )
        content = response.choices[0].message.content
        return json.loads(content) if content else None
    except Exception:
        logger.error(f"Error in structured OpenAI call: {traceback.format_exc()}")
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
