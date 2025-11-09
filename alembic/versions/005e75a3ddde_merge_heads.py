"""merge heads

Revision ID: 005e75a3ddde
Revises: 0d60df80166b, f5d5db155a1a
Create Date: 2025-11-08 21:39:35.275301

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005e75a3ddde'
down_revision = ('0d60df80166b', 'f5d5db155a1a')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
