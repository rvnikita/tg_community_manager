import requests
import traceback

from src.config_helper import get_config
from src.db_helper import session_scope, Message_Log
from src.logging_helper import get_logger

# Configure logger
logger = get_logger()

# Load configuration
config = get_config()
OPENAI_API_KEY = config.get('OPENAI', 'KEY')
OPENAI_MODEL = config.get('OPENAI', 'EMBEDDING_MODEL')

#TODO:MED We should rewrite this script with the use of openai_helper.py and better db_helper.py usage

def get_openai_embedding(text):
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
