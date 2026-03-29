"""Add income_category field to community_users table

Revision ID: add_income_category
Revises: add_assessment_case_severity, add_profile_fields_community
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_income_category'
down_revision = ('add_assessment_case_severity', 'add_profile_fields_community')
branch_labels = None
depends_on = None


def upgrade():
    # Add income_category column to community_users table
    op.add_column('community_users', sa.Column('income_category', sa.String(50), nullable=True))
    # Create index for better query performance
    op.create_index(op.f('ix_community_users_income_category'), 'community_users', ['income_category'], unique=False)
    
    # Populate income_category based on existing family_annual_income values
    connection = op.get_bind()
    
    # For income <= 10,000: set as "Indigent Families"
    connection.execute(
        sa.text("""
            UPDATE community_users 
            SET income_category = 'Indigent Families' 
            WHERE family_annual_income IS NOT NULL AND family_annual_income <= 10000
        """)
    )
    
    # For income 10,001 - 30,000: set as "Low Income Families"
    connection.execute(
        sa.text("""
            UPDATE community_users 
            SET income_category = 'Low Income Families' 
            WHERE family_annual_income IS NOT NULL AND family_annual_income > 10000 AND family_annual_income <= 30000
        """)
    )


def downgrade():
    # Drop the index first
    op.drop_index(op.f('ix_community_users_income_category'), table_name='community_users')
    # Drop the column
    op.drop_column('community_users', 'income_category')
