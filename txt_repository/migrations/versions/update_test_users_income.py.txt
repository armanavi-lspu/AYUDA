"""Update test users income to 20000-40000 range

Revision ID: update_test_users_income
Revises: dummy_data_001
Create Date: 2026-03-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'update_test_users_income'
down_revision = 'dummy_data_001'
branch_labels = None
depends_on = None


def upgrade():
    """Update family_annual_income for all test users to be between 20,000-40,000"""
    op.execute("""
        UPDATE community_users
        SET family_annual_income = (
            20000 + (random() * 20000)::int
        )
        WHERE user_id IN (
            SELECT id FROM users 
            WHERE role = 'community' AND email LIKE 'user%@test.com'
        )
    """)


def downgrade():
    """Revert income changes - no specific downgrade since original values varied"""
    pass
