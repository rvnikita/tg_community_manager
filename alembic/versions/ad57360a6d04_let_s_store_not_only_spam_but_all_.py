"""Let's store not only spam, but all messages and only mark spam ones

Revision ID: ad57360a6d04
Revises: 4ea451ee3e7a
Create Date: 2024-04-30 15:22:16.665833

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'ad57360a6d04'
down_revision = '4ea451ee3e7a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table('tg_spam_report_log', 'tg_message_log')

    op.add_column('tg_message_log', sa.Column('is_spam', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    #rename the columns
    op.alter_column('tg_message_log', 'admin_id', new_column_name='reporting_id')
    op.alter_column('tg_message_log', 'admin_nickname', new_column_name='reporting_id_nickname')

def downgrade() -> None:
    op.alter_column('tg_message_log', 'reporting_id', new_column_name='admin_id')
    op.alter_column('tg_message_log', 'reporting_id_nickname', new_column_name='admin_nickname')

    op.drop_column('tg_message_log', 'is_spam')

    op.rename_table('tg_message_log', 'tg_spam_report_log')
