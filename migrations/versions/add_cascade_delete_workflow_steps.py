"""Add ON DELETE CASCADE to application_workflow_status foreign key

Revision ID: add_cascade_delete_workflow
Revises: 7fa123a78a51
Create Date: 2026-02-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_cascade_delete_workflow'
down_revision = '7fa123a78a51'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the existing foreign key constraint
    with op.batch_alter_table('application_workflow_status', schema=None) as batch_op:
        batch_op.drop_constraint('application_workflow_status_workflow_step_id_fkey', type_='foreignkey')
        # Re-create it with ON DELETE CASCADE
        batch_op.create_foreign_key(
            'application_workflow_status_workflow_step_id_fkey',
            'program_workflow_steps',
            ['workflow_step_id'],
            ['id'],
            ondelete='CASCADE'
        )


def downgrade():
    # Revert to the original foreign key without CASCADE
    with op.batch_alter_table('application_workflow_status', schema=None) as batch_op:
        batch_op.drop_constraint('application_workflow_status_workflow_step_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'application_workflow_status_workflow_step_id_fkey',
            'program_workflow_steps',
            ['workflow_step_id'],
            ['id']
        )
