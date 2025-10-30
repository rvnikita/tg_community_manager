"""Add composite index on tg_report (chat_id, reported_user_id) where reason is not null

Revision ID: 0d60df80166b
Revises: 5b25c90fc5fb
Create Date: 2025-05-29 14:13:00.382204

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0d60df80166b'
down_revision = '5b25c90fc5fb'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tg_report_chatid_userid_reason
        ON public.tg_report (chat_id, reported_user_id)
        WHERE reason IS NOT NULL;
        """
    )

def downgrade():
    op.execute(
        """
        DROP INDEX IF EXISTS ix_tg_report_chatid_userid_reason;
        """
    )