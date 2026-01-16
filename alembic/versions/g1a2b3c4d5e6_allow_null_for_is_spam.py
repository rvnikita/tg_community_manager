"""Allow NULL for is_spam column

Revision ID: g1a2b3c4d5e6
Revises: f5d5db155a1a
Create Date: 2025-01-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g1a2b3c4d5e6'
down_revision = '2ad780459804'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Allow NULL for is_spam - NULL means unknown, False means not spam, True means spam
    op.alter_column('tg_message_log', 'is_spam',
                    existing_type=sa.BOOLEAN(),
                    nullable=True)


def downgrade() -> None:
    # First set any NULL values to False before adding NOT NULL constraint
    op.execute("UPDATE tg_message_log SET is_spam = FALSE WHERE is_spam IS NULL")
    op.alter_column('tg_message_log', 'is_spam',
                    existing_type=sa.BOOLEAN(),
                    nullable=False)
