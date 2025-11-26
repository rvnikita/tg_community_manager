"""add_indexes_for_spam_training_query

Revision ID: 2e3839bc11fb
Revises: 8b083406d2f8
Create Date: 2025-11-25 20:46:54.756783

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2e3839bc11fb'
down_revision = '8b083406d2f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index for manually_verified filter (used in WHERE clause)
    op.create_index('ix_tg_message_log_manually_verified', 'tg_message_log', ['manually_verified'])

    # Index for spam_prediction_probability range queries (> 0.99 or < 0.01)
    op.create_index('ix_tg_message_log_spam_prediction_probability', 'tg_message_log', ['spam_prediction_probability'])

    # Index for is_spam filter (used in WHERE and subquery GROUP BY)
    op.create_index('ix_tg_message_log_is_spam', 'tg_message_log', ['is_spam'])

    # Partial index on embedding (only where NOT NULL) - most impactful for the query
    op.execute(
        'CREATE INDEX ix_tg_message_log_embedding_not_null ON tg_message_log (id) WHERE embedding IS NOT NULL'
    )

    # Composite index for the common filter combination (manually_verified OR spam_prediction extremes)
    # This helps PostgreSQL optimize the OR condition
    op.create_index(
        'ix_tg_message_log_training_filter',
        'tg_message_log',
        ['manually_verified', 'spam_prediction_probability', 'is_spam']
    )


def downgrade() -> None:
    op.drop_index('ix_tg_message_log_training_filter', table_name='tg_message_log')
    op.drop_index('ix_tg_message_log_embedding_not_null', table_name='tg_message_log')
    op.drop_index('ix_tg_message_log_is_spam', table_name='tg_message_log')
    op.drop_index('ix_tg_message_log_spam_prediction_probability', table_name='tg_message_log')
    op.drop_index('ix_tg_message_log_manually_verified', table_name='tg_message_log')
