"""Add enable_application_slip column to programs table"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_application_slip_toggle'
down_revision = 'remove_min_items_workflow'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('programs', sa.Column('enable_application_slip', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column('programs', 'enable_application_slip')
