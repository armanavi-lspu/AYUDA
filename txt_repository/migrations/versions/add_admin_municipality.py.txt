"""Add municipality field to admin_users

Revision ID: add_admin_municipality
Revises: multiple_copy_types
Create Date: 2026-04-05 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_admin_municipality'
down_revision = 'multiple_copy_types'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('admin_users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('municipality', sa.String(length=100), nullable=True))
        batch_op.create_index(batch_op.f('ix_admin_users_municipality'), ['municipality'], unique=False)


def downgrade():
    with op.batch_alter_table('admin_users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_admin_users_municipality'))
        batch_op.drop_column('municipality')
