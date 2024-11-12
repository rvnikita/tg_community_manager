import sys
import os
import asyncio
import psycopg2
import psycopg2.extras
import numpy as np
import traceback
from datetime import datetime, timezone
import openai




current_dir = os.path.dirname(os.path.abspath(__file__))  # src/cron
project_root = os.path.dirname(os.path.dirname(current_dir))  # tg_community_manager
sys.path.insert(0, project_root)

# Import your helper modules
import src.logging_helper as logging_helper
import src.config_helper as config_helper
import src.openai_helper as openai_helper
import src.db_helper as db_helper
import src.spamcheck_helper as spamcheck_helper  # Assuming generate_features is in this module
import src.rating_helper as rating_helper

# Configure logger and load config
logger = logging_helper.get_logger()
config = config_helper.get_config()

# Set OpenAI API key
openai.api_key = config['OPENAI']['KEY']

async def update_embeddings():
    conn = None
    try:
        conn = psycopg2.connect(
            user=config['DB']['DB_USER'],
            password=config['DB']['DB_PASSWORD'],
            host=config['DB']['DB_HOST'],
            port=config['DB']['DB_PORT'],
            database=config['DB']['DB_DATABASE']
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        batch_size = 100
        processed_count = 0

        while True:
            # Fetch up to 100 messages without embeddings
            sql_select = """
                SELECT id, user_id, chat_id, message_content, is_forwarded, reply_to_message_id
                FROM tg_message_log
                WHERE embedding IS NULL AND message_content IS NOT NULL
                LIMIT %s
            """
            cur.execute(sql_select, (batch_size,))
            rows = cur.fetchall()

            if not rows:
                logger.info("No more messages found without embeddings.")
                break

            logger.info(f"Processing {len(rows)} messages.")

            for row in rows:
                message_id = row['id']
                user_id = row['user_id']
                chat_id = row['chat_id']
                message_content = row['message_content']
                is_forwarded = row.get('is_forwarded')
                reply_to_message_id = row.get('reply_to_message_id')

                # Skip empty message contents
                if not message_content.strip():
                    logger.warning(f"Message ID {message_id} has empty content. Skipping.")
                    continue

                try:
                    # Generate features (embedding is part of the features)
                    feature_array = await spamcheck_helper.generate_features(
                        user_id=user_id,
                        chat_id=chat_id,
                        message_text=message_content,
                        is_forwarded=is_forwarded,
                        reply_to_message_id=reply_to_message_id
                    )

                    if feature_array is None:
                        logger.error(f"Feature array is None for message ID {message_id}. Skipping.")
                        continue

                    # Extract the embedding from the feature array
                    NUM_ADDITIONAL_FEATURES = 9  # Update based on your generate_features function
                    embedding = feature_array[:-NUM_ADDITIONAL_FEATURES]

                    # Convert the embedding to a list for psycopg2
                    embedding_list = embedding.tolist()

                    # Update the embedding in the database
                    sql_update = """
                        UPDATE tg_message_log
                        SET embedding = %s
                        WHERE id = %s
                    """
                    cur.execute(sql_update, (embedding_list, message_id))
                    conn.commit()

                    # logger.info(f"Updated embedding for message ID {message_id}.")
                    processed_count += 1

                except openai.error.OpenAIError as e:
                    logger.error(f"OpenAI API error for message ID {message_id}: {e}")
                    # Optionally, implement a retry mechanism or exponential backoff here

                except Exception as e:
                    logger.error(f"Error processing message ID {message_id}: {traceback.format_exc()}")
                    # Optionally, handle specific exceptions or log them

            logger.info(f"Batch processing completed. Total messages processed so far: {processed_count}")

        logger.info("Embedding update process completed.")

    except (Exception, psycopg2.DatabaseError) as error:
        logger.error(f"Database error: {traceback.format_exc()}")
    finally:
        if conn is not None:
            conn.close()
            logger.info("Database connection closed.")

if __name__ == '__main__':
    asyncio.run(update_embeddings())
