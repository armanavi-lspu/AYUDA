"""Add cancellation request fields to applications table

Revision ID: add_cancellation_request
Revises: 
Create Date: 2024-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_cancellation_request'
down_revision = 'add_application_slip_toggle'

def upgrade():
    # Add cancellation request columns to applications table
    op.add_column('applications', sa.Column('cancellation_requested', sa.Boolean(), nullable=True, default=False))
    op.add_column('applications', sa.Column('cancellation_reason', sa.Text(), nullable=True))
    op.add_column('applications', sa.Column('cancellation_requested_at', sa.DateTime(), nullable=True))
    op.add_column('applications', sa.Column('cancellation_status', sa.String(20), nullable=True))
    op.add_column('applications', sa.Column('cancellation_reviewed_by', sa.Integer(), nullable=True))
    op.add_column('applications', sa.Column('cancellation_reviewed_at', sa.DateTime(), nullable=True))
    op.add_column('applications', sa.Column('cancellation_admin_notes', sa.Text(), nullable=True))
    
    # Add foreign key constraint for cancellation_reviewed_by
    op.create_foreign_key(
        'fk_applications_cancellation_reviewed_by',
        'applications', 'users',
        ['cancellation_reviewed_by'], ['id']
    )
    
    # Update existing records to have cancellation_requested = False
    op.execute("UPDATE applications SET cancellation_requested = FALSE WHERE cancellation_requested IS NULL")


def downgrade():
    # Remove foreign key constraint
    op.drop_constraint('fk_applications_cancellation_reviewed_by', 'applications', type_='foreignkey')
    
    # Drop columns
    op.drop_column('applications', 'cancellation_admin_notes')
    op.drop_column('applications', 'cancellation_reviewed_at')
    op.drop_column('applications', 'cancellation_reviewed_by')
    op.drop_column('applications', 'cancellation_status')
    op.drop_column('applications', 'cancellation_requested_at')
    op.drop_column('applications', 'cancellation_reason')
    op.drop_column('applications', 'cancellation_requested')
