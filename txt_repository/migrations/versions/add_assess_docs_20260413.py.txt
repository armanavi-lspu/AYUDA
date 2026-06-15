"""Ensure assessment_documents table exists

Revision ID: add_assess_docs_20260413
Revises: seed_muni_admins_20260411
Create Date: 2026-04-13 09:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_assess_docs_20260413'
down_revision = 'seed_muni_admins_20260411'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _index_names(inspector, table_name):
    return {index['name'] for index in inspector.get_indexes(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'assessment_documents'):
        op.create_table(
            'assessment_documents',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('assessment_id', sa.Integer(), nullable=False),
            sa.Column('file_path', sa.String(length=255), nullable=False),
            sa.Column('original_filename', sa.String(length=255), nullable=False),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('file_type', sa.String(length=100), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('uploaded_by', sa.Integer(), nullable=False),
            sa.Column('uploaded_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )

    inspector = sa.inspect(bind)
    index_names = _index_names(inspector, 'assessment_documents') if _table_exists(inspector, 'assessment_documents') else set()
    if 'ix_assessment_documents_assessment_id' not in index_names:
        op.create_index(
            'ix_assessment_documents_assessment_id',
            'assessment_documents',
            ['assessment_id'],
            unique=False
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, 'assessment_documents'):
        op.drop_table('assessment_documents')
