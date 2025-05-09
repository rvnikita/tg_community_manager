"""change reply_to_message_id to trigger_id

Revision ID: 6b0e1f469325
Revises: cd3c4aef762f
Create Date: 2024-02-22 20:05:59.055283

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b0e1f469325'
down_revision = 'cd3c4aef762f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('tg_message_deletion', sa.Column('trigger_id', sa.BigInteger(), nullable=True))
    op.drop_column('tg_message_deletion', 'reply_to_message_id')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('tg_message_deletion', sa.Column('reply_to_message_id', sa.BIGINT(), autoincrement=False, nullable=True))
    op.drop_column('tg_message_deletion', 'trigger_id')
    # ### end Alembic commands ###
