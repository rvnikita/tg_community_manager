import requests
import traceback
import os

from src.db_helper import session_scope, Message_Log
from src.logging_helper import get_logger
import src.openai_helper as openai_helper

# Configure logger
logger = get_logger()

OPENAI_API_KEY = os.getenv('ENV_OPENAI_KEY')
OPENAI_MODEL = os.getenv('ENV_OPENAI_MODEL')

#TODO:MED We should rewrite this script with the use of openai_helper.py and better db_helper.py usage



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
                embedding = openai_helper.generate_embedding(message.message_content)
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
