"""add is_verified to user for spam bypass

Revision ID: a1b2c3d4e5f6
Revises: 8b083406d2f8
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '2e3839bc11fb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tg_user', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.sql.expression.False_()))


def downgrade() -> None:
    op.drop_column('tg_user', 'is_verified')
