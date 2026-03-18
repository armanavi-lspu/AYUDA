"""Add case severity fields to assessments

Revision ID: add_assessment_case_severity
Revises: add_areas_concern
Create Date: 2026-03-19 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_assessment_case_severity'
down_revision = 'add_areas_concern'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('case_severity', sa.String(length=20), nullable=False, server_default='unrated'))
        batch_op.add_column(sa.Column('severity_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('severity_factors', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('severity_justification', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('severity_updated_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('severity_updated_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_assessments_case_severity', ['case_severity'], unique=False)
        batch_op.create_index('ix_assessments_severity_score', ['severity_score'], unique=False)
        batch_op.create_foreign_key(
            'fk_assessments_severity_updated_by_users',
            'users',
            ['severity_updated_by'],
            ['id']
        )


def downgrade():
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_assessments_severity_updated_by_users', type_='foreignkey')
        batch_op.drop_index('ix_assessments_severity_score')
        batch_op.drop_index('ix_assessments_case_severity')
        batch_op.drop_column('severity_updated_at')
        batch_op.drop_column('severity_updated_by')
        batch_op.drop_column('severity_justification')
        batch_op.drop_column('severity_factors')
        batch_op.drop_column('severity_score')
        batch_op.drop_column('case_severity')
