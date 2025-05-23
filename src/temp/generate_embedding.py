#!/usr/bin/env python
import sys
import os
import re
from datetime import datetime, timezone
import src.openai_helper as openai_helper
import src.logging_helper as logging_helper

logger = logging_helper.get_logger()

def main():
    # Change this sample text as needed.
    sample_text = (
        "От 150 долларов в день. Пишите в личку"
    )
    
    try:
        # Generate embedding using your helper.
        embedding = openai_helper.generate_embedding(sample_text)
        
        # Convert the embedding (assumed to be a list of floats) to a PostgreSQL vector literal.
        embedding_str = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
        
        # Parameters
        threshold = 0.97
        limit = 100

        # Build a non-nested SQL query string.
        sql = (
            "SELECT \n"
            "    id,\n"
            "    message_id,\n"
            "    chat_id,\n"
            "    is_spam,\n"
            "    manually_verified,\n"
            "    message_content,\n"
            "    embedding,\n"
            f"    embedding <-> '{embedding_str}'::vector AS distance\n"
            "FROM tg_message_log\n"
            "WHERE is_spam = false\n"
            f"  AND embedding <-> '{embedding_str}'::vector < {threshold}\n"
            f"ORDER BY embedding <-> '{embedding_str}'::vector ASC\n"
            f"LIMIT {limit};"
        )
        
        # print("Copy and run the following SQL query:")
        print(sql)
    except Exception as e:
        logger.error("Error generating embedding or building SQL: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
