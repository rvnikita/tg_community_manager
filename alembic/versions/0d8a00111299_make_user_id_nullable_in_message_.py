"""make user_id nullable in Message_Deletion

Revision ID: 0d8a00111299
Revises: 6b0e1f469325
Create Date: 2024-02-23 07:37:13.560870

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0d8a00111299'
down_revision = '6b0e1f469325'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('tg_message_deletion', 'user_id',
               existing_type=sa.BIGINT(),
               nullable=True)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('tg_message_deletion', 'user_id',
               existing_type=sa.BIGINT(),
               nullable=False)
    # ### end Alembic commands ###