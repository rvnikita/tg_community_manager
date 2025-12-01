#!/usr/bin/env python3
"""Add like_reactions and dislike_reactions to default chat config (chat_id=0)"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv('config/.env')

# Add project root to path
project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.append(os.path.abspath(project_root))

from src.helpers.db_helper import Session, Chat

def add_reaction_config():
    """Add reaction config to default chat (id=0)"""
    with Session() as session:
        # Get default chat (id=0)
        default_chat = session.query(Chat).filter(Chat.id == 0).first()

        if not default_chat:
            print("ERROR: Default chat (id=0) not found in database!")
            print("You need to create the default chat first.")
            return

        print(f"Found default chat (id=0)")
        print(f"Current config keys: {list(default_chat.config.keys())}")

        # Check if already has the config
        if 'like_reactions' in default_chat.config:
            print(f"\n✓ like_reactions already exists: {default_chat.config['like_reactions']}")
        else:
            default_chat.config['like_reactions'] = ["👍", "❤️"]
            print(f"\n✓ Added like_reactions: {default_chat.config['like_reactions']}")

        if 'dislike_reactions' in default_chat.config:
            print(f"✓ dislike_reactions already exists: {default_chat.config['dislike_reactions']}")
        else:
            default_chat.config['dislike_reactions'] = ["👎"]
            print(f"✓ Added dislike_reactions: {default_chat.config['dislike_reactions']}")

        # Mark as modified (for JSONB field)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(default_chat, "config")

        # Commit changes
        session.commit()
        print("\n✅ Successfully updated default chat config!")
        print("\nNote: You may need to restart the bot or wait for the cache to expire (3600s)")

if __name__ == "__main__":
    add_reaction_config()
