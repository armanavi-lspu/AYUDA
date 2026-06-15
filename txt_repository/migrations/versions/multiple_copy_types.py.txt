"""Add support for multiple copy types per requirement - merge branches

Revision ID: multiple_copy_types
Revises: add_document_copy_requirements, add_income_category
Create Date: 2026-03-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'multiple_copy_types'
down_revision = ('add_document_copy_requirements', 'add_income_category')
branch_labels = None
depends_on = None


def upgrade():
    # Change copy_type from VARCHAR(50) to TEXT to store JSON
    op.alter_column('program_requirements', 'copy_type',
                    existing_type=sa.String(50),
                    type_=sa.Text(),
                    existing_nullable=False,
                    existing_server_default='original')
    
    # Remove number_of_copies column since it will be part of the JSON structure
    op.drop_column('program_requirements', 'number_of_copies')


def downgrade():
    # Add number_of_copies back
    op.add_column('program_requirements', 
                  sa.Column('number_of_copies', sa.Integer(), nullable=False, server_default='1'))
    
    # Change copy_type back to VARCHAR
    op.alter_column('program_requirements', 'copy_type',
                    existing_type=sa.Text(),
                    type_=sa.String(50),
                    existing_nullable=False,
                    existing_server_default='original')
