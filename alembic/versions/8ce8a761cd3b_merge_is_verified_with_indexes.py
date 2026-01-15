"""merge_is_verified_with_indexes

Revision ID: 8ce8a761cd3b
Revises: 2e3839bc11fb, a1b2c3d4e5f6
Create Date: 2026-01-15 12:31:51.290319

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8ce8a761cd3b'
down_revision = ('2e3839bc11fb', 'a1b2c3d4e5f6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
