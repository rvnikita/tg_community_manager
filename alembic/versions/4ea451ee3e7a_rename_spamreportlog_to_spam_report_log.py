"""rename SpamReportLog to Spam_Report_Log

Revision ID: 4ea451ee3e7a
Revises: 09a8065b33e6
Create Date: 2024-04-02 19:40:17.914542

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '4ea451ee3e7a'
down_revision = '09a8065b33e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.rename_table('tg_spamreportlog', 'tg_spam_report_log')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.rename_table('tg_spam_report_log', 'tg_spamreportlog')
    # ### end Alembic commands ###
