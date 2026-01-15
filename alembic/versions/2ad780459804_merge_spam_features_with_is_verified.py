"""merge spam features with is_verified

Revision ID: 2ad780459804
Revises: 8ce8a761cd3b, b2c3d4e5f6a7
Create Date: 2026-01-15 16:52:45.502407

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2ad780459804'
down_revision = ('8ce8a761cd3b', 'b2c3d4e5f6a7')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
