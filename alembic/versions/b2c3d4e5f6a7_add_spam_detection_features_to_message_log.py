"""add spam detection features to message_log

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2025-01-15 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns for spam detection features
    op.add_column('tg_message_log', sa.Column('has_video', sa.Boolean(), nullable=True))
    op.add_column('tg_message_log', sa.Column('has_document', sa.Boolean(), nullable=True))
    op.add_column('tg_message_log', sa.Column('has_photo', sa.Boolean(), nullable=True))
    op.add_column('tg_message_log', sa.Column('forwarded_from_channel', sa.Boolean(), nullable=True))
    op.add_column('tg_message_log', sa.Column('has_link', sa.Boolean(), nullable=True))
    op.add_column('tg_message_log', sa.Column('entity_count', sa.Integer(), nullable=True))

    # Backfill from raw_message JSON where available
    # Only update rows where raw_message is not null
    op.execute("""
        UPDATE tg_message_log
        SET
            has_video = CASE
                WHEN raw_message IS NULL THEN NULL
                ELSE (raw_message ? 'animation' OR raw_message ? 'video')
            END,
            has_document = CASE
                WHEN raw_message IS NULL THEN NULL
                ELSE (raw_message ? 'document')
            END,
            has_photo = CASE
                WHEN raw_message IS NULL THEN NULL
                ELSE (raw_message ? 'photo')
            END,
            forwarded_from_channel = CASE
                WHEN raw_message IS NULL THEN NULL
                WHEN raw_message->'forward_from_chat'->>'type' = 'channel' THEN true
                WHEN raw_message ? 'forward_from_chat' THEN false
                ELSE NULL
            END,
            has_link = CASE
                WHEN raw_message IS NULL THEN NULL
                ELSE (
                    EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(COALESCE(raw_message->'entities', '[]'::jsonb)) AS e
                        WHERE e->>'type' IN ('url', 'text_link')
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(COALESCE(raw_message->'caption_entities', '[]'::jsonb)) AS e
                        WHERE e->>'type' IN ('url', 'text_link')
                    )
                )
            END,
            entity_count = CASE
                WHEN raw_message IS NULL THEN NULL
                ELSE COALESCE(jsonb_array_length(raw_message->'entities'), 0)
                     + COALESCE(jsonb_array_length(raw_message->'caption_entities'), 0)
            END
        WHERE raw_message IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column('tg_message_log', 'entity_count')
    op.drop_column('tg_message_log', 'has_link')
    op.drop_column('tg_message_log', 'forwarded_from_channel')
    op.drop_column('tg_message_log', 'has_photo')
    op.drop_column('tg_message_log', 'has_document')
    op.drop_column('tg_message_log', 'has_video')
