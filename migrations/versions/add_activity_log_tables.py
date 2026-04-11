"""Add missing activity log tables

Revision ID: add_activity_logs_20260411
Revises: add_occ_sector_20260411
Create Date: 2026-04-11 13:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_activity_logs_20260411'
down_revision = 'add_occ_sector_20260411'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _index_names(inspector, table_name):
    return {index['name'] for index in inspector.get_indexes(table_name)}


def _create_missing_index(table_name, index_name, columns, unique=False):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, table_name):
        return

    existing_indexes = _index_names(inspector, table_name)
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'admin_activity_logs'):
        op.create_table(
            'admin_activity_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('admin_id', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(length=50), nullable=False),
            sa.Column('action_type', sa.String(length=20), nullable=False, server_default='update'),
            sa.Column('entity_type', sa.String(length=50), nullable=False),
            sa.Column('entity_id', sa.Integer(), nullable=True),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['admin_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists(inspector, 'user_activity_logs'):
        op.create_table(
            'user_activity_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(length=50), nullable=False),
            sa.Column('action_type', sa.String(length=20), nullable=False, server_default='view'),
            sa.Column('entity_type', sa.String(length=50), nullable=False),
            sa.Column('entity_id', sa.Integer(), nullable=True),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    # Admin activity log indexes
    _create_missing_index('admin_activity_logs', 'ix_admin_activity_logs_admin_id', ['admin_id'])
    _create_missing_index('admin_activity_logs', 'ix_admin_activity_logs_action', ['action'])
    _create_missing_index('admin_activity_logs', 'ix_admin_activity_logs_action_type', ['action_type'])
    _create_missing_index('admin_activity_logs', 'ix_admin_activity_logs_entity_type', ['entity_type'])
    _create_missing_index('admin_activity_logs', 'ix_admin_activity_logs_created_at', ['created_at'])
    _create_missing_index('admin_activity_logs', 'idx_activity_admin_date', ['admin_id', 'created_at'])
    _create_missing_index('admin_activity_logs', 'idx_activity_entity', ['entity_type', 'entity_id'])

    # User activity log indexes
    _create_missing_index('user_activity_logs', 'ix_user_activity_logs_user_id', ['user_id'])
    _create_missing_index('user_activity_logs', 'ix_user_activity_logs_action', ['action'])
    _create_missing_index('user_activity_logs', 'ix_user_activity_logs_action_type', ['action_type'])
    _create_missing_index('user_activity_logs', 'ix_user_activity_logs_entity_type', ['entity_type'])
    _create_missing_index('user_activity_logs', 'ix_user_activity_logs_created_at', ['created_at'])
    _create_missing_index('user_activity_logs', 'idx_user_activity_user_date', ['user_id', 'created_at'])
    _create_missing_index('user_activity_logs', 'idx_user_activity_entity', ['entity_type', 'entity_id'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, 'user_activity_logs'):
        for index_name in [
            'idx_user_activity_entity',
            'idx_user_activity_user_date',
            'ix_user_activity_logs_created_at',
            'ix_user_activity_logs_entity_type',
            'ix_user_activity_logs_action_type',
            'ix_user_activity_logs_action',
            'ix_user_activity_logs_user_id',
        ]:
            if index_name in _index_names(inspector, 'user_activity_logs'):
                op.drop_index(index_name, table_name='user_activity_logs')
                inspector = sa.inspect(bind)
        op.drop_table('user_activity_logs')
        inspector = sa.inspect(bind)

    if _table_exists(inspector, 'admin_activity_logs'):
        for index_name in [
            'idx_activity_entity',
            'idx_activity_admin_date',
            'ix_admin_activity_logs_created_at',
            'ix_admin_activity_logs_entity_type',
            'ix_admin_activity_logs_action_type',
            'ix_admin_activity_logs_action',
            'ix_admin_activity_logs_admin_id',
        ]:
            if index_name in _index_names(inspector, 'admin_activity_logs'):
                op.drop_index(index_name, table_name='admin_activity_logs')
                inspector = sa.inspect(bind)
        op.drop_table('admin_activity_logs')
