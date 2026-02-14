"""Remove min_items column from program_workflow_steps

Revision ID: remove_min_items_workflow
Revises: add_cascade_delete_workflow
Create Date: 2026-02-11 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'remove_min_items_workflow'
down_revision = 'add_cascade_delete_workflow'
branch_labels = None
depends_on = None


def upgrade():
    # Remove the min_items column from program_workflow_steps
    with op.batch_alter_table('program_workflow_steps', schema=None) as batch_op:
        batch_op.drop_column('min_items')


def downgrade():
    # Re-add the min_items column if rolling back
    with op.batch_alter_table('program_workflow_steps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('min_items', sa.Integer(), server_default='1', nullable=True))
