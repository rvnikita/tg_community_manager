"""Add благодарю to default like_words

Revision ID: a1b2c3d4e5f6
Revises: 005e75a3ddde
Create Date: 2025-11-24

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '005e75a3ddde'
branch_labels = None
depends_on = None

NEW_WORD = 'благодарю'


def upgrade() -> None:
    # Add 'благодарю' to like_words in default chat (id=0) config
    # Using PostgreSQL JSONB array append, but only if the word doesn't already exist
    op.execute(f"""
        UPDATE tg_chat
        SET config = jsonb_set(
            config,
            '{{like_words}}',
            COALESCE(config->'like_words', '[]'::jsonb) || '"{NEW_WORD}"'::jsonb
        )
        WHERE id = 0
          AND NOT (COALESCE(config->'like_words', '[]'::jsonb) @> '"{NEW_WORD}"'::jsonb)
    """)


def downgrade() -> None:
    # Remove 'благодарю' from like_words in default chat (id=0) config
    op.execute(f"""
        UPDATE tg_chat
        SET config = jsonb_set(
            config,
            '{{like_words}}',
            (config->'like_words') - '{NEW_WORD}'
        )
        WHERE id = 0
    """)
