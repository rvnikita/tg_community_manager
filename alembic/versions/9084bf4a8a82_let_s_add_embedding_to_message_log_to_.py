"""Let's add embedding to message_log to teach ML in future

Revision ID: 9084bf4a8a82
Revises: 2b6d173b7958
Create Date: 2024-05-01 00:02:00.105666

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision = '9084bf4a8a82'
down_revision = '2b6d173b7958'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    conn = op.get_bind()
    conn.execute(sa.sql.text("CREATE EXTENSION IF NOT EXISTS vector;"))

    op.add_column('tg_message_log', sa.Column('embedding', pgvector.sqlalchemy.Vector(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('tg_message_log', 'embedding')
    # ### end Alembic commands ###