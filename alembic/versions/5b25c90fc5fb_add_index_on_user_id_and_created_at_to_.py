"""add index on user_id and created_at to tg_message_log

Revision ID: 5b25c90fc5fb
Revises: 99f88cbbaaef
Create Date: 2025-05-28 18:39:16.368135

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b25c90fc5fb'
down_revision = '99f88cbbaaef'
branch_labels = None
depends_on = None


def upgrade():
    # If your models are defined elsewhere, you can just use the raw name here
    op.create_index(
        'idx_tg_message_log_user_id_created_at',
        'tg_message_log',
        ['user_id', 'created_at'],
        unique=False
    )

def downgrade():
    op.drop_index('idx_tg_message_log_user_id_created_at', table_name='tg_message_log')
