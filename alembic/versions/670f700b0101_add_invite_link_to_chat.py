"""add invite link to chat

Revision ID: 670f700b0101
Revises: b27cde79a360
Create Date: 2023-07-16 17:52:41.761460

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '670f700b0101'
down_revision = 'b27cde79a360'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('tg_chat', sa.Column('invite_link', sa.String(), server_default=sa.text("''::character varying"), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('tg_chat', 'invite_link')
    # ### end Alembic commands ###
