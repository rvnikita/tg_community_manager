"""Update scheduled message models

Revision ID: 2422f509a134
Revises: 0f15d2e4ada6
Create Date: 2024-11-15 13:26:03.222652

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2422f509a134'
down_revision = '0f15d2e4ada6'
branch_labels = None
depends_on = None


def upgrade():
    # ### Begin custom migration code ###

    # 1. Rename 'tg_scheduled_message' to 'tg_scheduled_message_config'
    op.rename_table('tg_scheduled_message', 'tg_scheduled_message_config')

    # 2. Create new table 'tg_scheduled_message_content'
    op.create_table(
        'tg_scheduled_message_content',
        sa.Column('id', sa.BigInteger(), sa.Identity(start=1, increment=1), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('parse_mode', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='scheduled_message_content_pkey')
    )

    # 3. Add 'message_content_id' column to 'tg_scheduled_message_config'
    op.add_column('tg_scheduled_message_config', sa.Column('message_content_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_scheduled_message_config_message_content',
        'tg_scheduled_message_config',
        'tg_scheduled_message_content',
        ['message_content_id'],
        ['id']
    )

    # 4. Migrate data from 'message' column to 'tg_scheduled_message_content' and update 'message_content_id'
    connection = op.get_bind()

    # Fetch results as mappings to access columns by name
    scheduled_messages = connection.execute(
        sa.text("SELECT id, message FROM tg_scheduled_message_config")
    ).mappings().fetchall()

    for sm in scheduled_messages:
        # Insert message content into 'tg_scheduled_message_content'
        result = connection.execute(
            sa.text("""
                INSERT INTO tg_scheduled_message_content (content)
                VALUES (:content) RETURNING id
            """),
            {'content': sm['message']}
        )
        message_content_id = result.fetchone()[0]

        # Update 'message_content_id' in 'tg_scheduled_message_config'
        connection.execute(
            sa.text("""
                UPDATE tg_scheduled_message_config
                SET message_content_id = :message_content_id
                WHERE id = :id
            """),
            {'message_content_id': message_content_id, 'id': sm['id']}
        )

    # 5. Make 'message_content_id' not nullable
    op.alter_column('tg_scheduled_message_config', 'message_content_id', nullable=False)

    # 6. Add new columns 'status', 'error_message', and 'error_count'
    op.add_column('tg_scheduled_message_config', sa.Column('status', sa.String(), nullable=False, server_default='active'))
    op.add_column('tg_scheduled_message_config', sa.Column('error_message', sa.Text(), nullable=True))
    op.add_column('tg_scheduled_message_config', sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'))

    # 7. Migrate 'active' boolean to 'status' string
    # Map 'active' = True to 'status' = 'active', False to 'paused'
    connection.execute(sa.text("""
        UPDATE tg_scheduled_message_config
        SET status = CASE
            WHEN active = true THEN 'active'
            ELSE 'paused'
        END
    """))

    # 8. Drop the 'active' column
    op.drop_column('tg_scheduled_message_config', 'active')

    # 9. Drop the old 'message' column, as data has been moved
    op.drop_column('tg_scheduled_message_config', 'message')

    # Remove server defaults if necessary
    op.alter_column('tg_scheduled_message_config', 'status', server_default=None)
    op.alter_column('tg_scheduled_message_config', 'error_count', server_default=None)

    # ### End custom migration code ###


def downgrade():
    # ### Begin custom downgrade code ###

    # 1. Add back the 'message' column to 'tg_scheduled_message_config'
    op.add_column('tg_scheduled_message_config', sa.Column('message', sa.Text(), nullable=True))

    # 2. Migrate data back from 'tg_scheduled_message_content' to 'message' column
    connection = op.get_bind()

    # Fetch results as mappings
    scheduled_messages = connection.execute(
        sa.text("SELECT id, message_content_id FROM tg_scheduled_message_config")
    ).mappings().fetchall()

    for sm in scheduled_messages:
        # Get the content from 'tg_scheduled_message_content'
        content_result = connection.execute(
            sa.text("""
                SELECT content FROM tg_scheduled_message_content
                WHERE id = :id
            """),
            {'id': sm['message_content_id']}
        )
        content_row = content_result.fetchone()
        if content_row:
            content = content_row[0]
        else:
            content = None

        # Update 'message' column in 'tg_scheduled_message_config'
        connection.execute(
            sa.text("""
                UPDATE tg_scheduled_message_config
                SET message = :content
                WHERE id = :id
            """),
            {'content': content, 'id': sm['id']}
        )

    # 3. Drop the 'message_content_id' column and foreign key
    op.drop_constraint('fk_scheduled_message_config_message_content', 'tg_scheduled_message_config', type_='foreignkey')
    op.drop_column('tg_scheduled_message_config', 'message_content_id')

    # 4. Drop the 'tg_scheduled_message_content' table
    op.drop_table('tg_scheduled_message_content')

    # 5. Add back the 'active' column to 'tg_scheduled_message_config'
    op.add_column('tg_scheduled_message_config', sa.Column('active', sa.Boolean(), nullable=False, server_default='true'))

    # 6. Migrate 'status' back to 'active' boolean
    connection.execute(sa.text("""
        UPDATE tg_scheduled_message_config
        SET active = CASE
            WHEN status = 'active' THEN true
            ELSE false
        END
    """))

    # 7. Drop the new columns 'status', 'error_message', 'error_count'
    op.drop_column('tg_scheduled_message_config', 'error_count')
    op.drop_column('tg_scheduled_message_config', 'error_message')
    op.drop_column('tg_scheduled_message_config', 'status')

    # 8. Rename 'tg_scheduled_message_config' back to 'tg_scheduled_message'
    op.rename_table('tg_scheduled_message_config', 'tg_scheduled_message')

    # ### End custom downgrade code ###
