#!/usr/bin/env python3
"""Add 🔥 (fire/lit) emoji to like_reactions in default chat config (chat_id=0)"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv('config/.env')

# Add project root to path
project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.append(os.path.abspath(project_root))

from src.helpers.db_helper import Session, Chat
from sqlalchemy.orm.attributes import flag_modified

def add_fire_emoji():
    """Add 🔥 emoji to like_reactions in default chat (id=0)"""
    with Session() as session:
        # Get default chat (id=0)
        default_chat = session.query(Chat).filter(Chat.id == 0).first()

        if not default_chat:
            print("ERROR: Default chat (id=0) not found in database!")
            return

        print(f"Found default chat (id=0)")

        # Check current like_reactions
        if 'like_reactions' not in default_chat.config:
            print("ERROR: like_reactions not found in config!")
            return

        current_likes = default_chat.config['like_reactions']
        print(f"Current like_reactions: {current_likes}")

        # Add 🔥 if not already there
        if "🔥" in current_likes:
            print("\n✓ 🔥 already in like_reactions")
        else:
            current_likes.append("🔥")
            default_chat.config['like_reactions'] = current_likes

            # Mark as modified (for JSONB field)
            flag_modified(default_chat, "config")

            # Commit changes
            session.commit()
            print(f"\n✅ Added 🔥 to like_reactions!")
            print(f"New like_reactions: {default_chat.config['like_reactions']}")

if __name__ == "__main__":
    add_fire_emoji()
