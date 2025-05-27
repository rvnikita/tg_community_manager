import sys
sys.path.insert(0, '../') # add parent directory to the pat

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

import openai

import src.db_helper as db_helper
import src.logging_helper as logging_helper

logger = logging_helper.get_logger()

# Load env if needed
load_dotenv("config/.env")

openai.api_key = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

def get_openai_embedding(text):
    # Add your batching/cleaning as needed
    response = openai.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding

def update_missing_embeddings():
    with db_helper.session_scope() as session:
        triggers = session.query(db_helper.Embeddings_Auto_Reply_Trigger) \
            .filter(db_helper.Embeddings_Auto_Reply_Trigger.embedding == None) \
            .all()
        logger.info(f"Found {len(triggers)} triggers without embedding")

        updated = 0
        for trigger in triggers:
            try:
                embedding = get_openai_embedding(trigger.trigger_text)
                trigger.embedding = embedding
                updated += 1
            except Exception as e:
                logger.error(f"Failed to get embedding for '{trigger.trigger_text}': {e}")

        session.commit()
        logger.info(f"Updated {updated} embeddings")

if __name__ == "__main__":
    update_missing_embeddings()
