"""Add problems_identified column to assessments

Revision ID: add_assess_probs_20260420
Revises: add_assess_docs_20260413
Create Date: 2026-04-20 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_assess_probs_20260420'
down_revision = 'add_assess_docs_20260413'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name):
    return {column['name'] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'assessments'):
        return

    column_names = _column_names(inspector, 'assessments')
    if 'problems_identified' not in column_names:
        with op.batch_alter_table('assessments', schema=None) as batch_op:
            batch_op.add_column(sa.Column('problems_identified', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'assessments'):
        return

    column_names = _column_names(inspector, 'assessments')
    if 'problems_identified' in column_names:
        with op.batch_alter_table('assessments', schema=None) as batch_op:
            batch_op.drop_column('problems_identified')
