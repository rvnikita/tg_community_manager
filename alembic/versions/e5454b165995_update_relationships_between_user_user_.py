"""Update relationships between user, user_status and chat

Revision ID: e5454b165995
Revises: 
Create Date: 2023-03-27 13:35:28.230202

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e5454b165995'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('tg_user_status', 'chat_id',
               existing_type=sa.BIGINT(),
               nullable=False)
    op.create_index(op.f('ix_tg_user_status_chat_id'), 'tg_user_status', ['chat_id'], unique=False)
    op.create_index(op.f('ix_tg_user_status_user_id'), 'tg_user_status', ['user_id'], unique=False)
    op.create_foreign_key(None, 'tg_user_status', 'tg_chat', ['chat_id'], ['id'], onupdate='CASCADE', ondelete='CASCADE')
    op.create_foreign_key(None, 'tg_user_status', 'tg_user', ['user_id'], ['id'], onupdate='CASCADE', ondelete='CASCADE')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'tg_user_status', type_='foreignkey')
    op.drop_constraint(None, 'tg_user_status', type_='foreignkey')
    op.drop_index(op.f('ix_tg_user_status_user_id'), table_name='tg_user_status')
    op.drop_index(op.f('ix_tg_user_status_chat_id'), table_name='tg_user_status')
    op.alter_column('tg_user_status', 'chat_id',
               existing_type=sa.BIGINT(),
               nullable=True)
    # ### end Alembic commands ###