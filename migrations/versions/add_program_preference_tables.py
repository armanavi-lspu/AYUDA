"""Add missing program preference tables

Revision ID: add_program_prefs_20260411
Revises: add_activity_logs_20260411
Create Date: 2026-04-11 14:15:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_program_prefs_20260411'
down_revision = 'add_activity_logs_20260411'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'saved_programs'):
        op.create_table(
            'saved_programs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('program_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['program_id'], ['programs.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'program_id', name='uq_saved_program'),
        )

    if not _table_exists(inspector, 'hidden_programs'):
        op.create_table(
            'hidden_programs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('program_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['program_id'], ['programs.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'program_id', name='uq_hidden_program'),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, 'hidden_programs'):
        op.drop_table('hidden_programs')

    inspector = sa.inspect(bind)
    if _table_exists(inspector, 'saved_programs'):
        op.drop_table('saved_programs')
