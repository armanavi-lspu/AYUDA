"""Add occupation_sector column to community_users

Revision ID: add_occ_sector_20260411
Revises: add_subsidy_payouts
Create Date: 2026-04-11 12:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_occ_sector_20260411'
down_revision = 'add_subsidy_payouts'
branch_labels = None
depends_on = None


def _column_names(inspector, table_name):
    return {column['name'] for column in inspector.get_columns(table_name)}


def _index_names(inspector, table_name):
    return {index['name'] for index in inspector.get_indexes(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    column_names = _column_names(inspector, 'community_users')
    if 'occupation_sector' not in column_names:
        with op.batch_alter_table('community_users', schema=None) as batch_op:
            batch_op.add_column(sa.Column('occupation_sector', sa.String(length=100), nullable=True))

    inspector = sa.inspect(bind)
    index_names = _index_names(inspector, 'community_users')
    if 'ix_community_users_occupation_sector' not in index_names:
        with op.batch_alter_table('community_users', schema=None) as batch_op:
            batch_op.create_index('ix_community_users_occupation_sector', ['occupation_sector'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    index_names = _index_names(inspector, 'community_users')
    if 'ix_community_users_occupation_sector' in index_names:
        with op.batch_alter_table('community_users', schema=None) as batch_op:
            batch_op.drop_index('ix_community_users_occupation_sector')

    inspector = sa.inspect(bind)
    column_names = _column_names(inspector, 'community_users')
    if 'occupation_sector' in column_names:
        with op.batch_alter_table('community_users', schema=None) as batch_op:
            batch_op.drop_column('occupation_sector')
