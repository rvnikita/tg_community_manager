"""optimize

Revision ID: 0a0551281943
Revises: 670f700b0101
Create Date: 2023-07-18 13:50:53.676578

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0a0551281943'
down_revision = '670f700b0101'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index('ix_user_status_user_id', 'tg_user_status', ['user_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_user_status_user_id', table_name='tg_user_status')
    # ### end Alembic commands ###