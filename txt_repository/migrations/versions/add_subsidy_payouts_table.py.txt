"""Add subsidy payouts table

Revision ID: add_subsidy_payouts
Revises: add_admin_municipality
Create Date: 2026-04-06 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_subsidy_payouts'
down_revision = 'add_admin_municipality'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'subsidy_payouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('payout_id', sa.String(length=50), nullable=False),
        sa.Column('payout_datetime', sa.DateTime(), nullable=False),
        sa.Column('payout_location', sa.String(length=255), nullable=False),
        sa.Column('payout_notes', sa.Text(), nullable=True),
        sa.Column('category_key', sa.String(length=50), nullable=False),
        sa.Column('category_label', sa.String(length=100), nullable=False),
        sa.Column('beneficiary_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('beneficiary_snapshot', sa.Text(), nullable=False),
        sa.Column('beneficiary_list_text', sa.Text(), nullable=True),
        sa.Column('beneficiary_list_html', sa.Text(), nullable=True),
        sa.Column('suggested_title', sa.String(length=255), nullable=True),
        sa.Column('suggested_content', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('saved_in_system', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('saved_at', sa.DateTime(), nullable=True),
        sa.Column('announcement_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['announcement_id'], ['announcements.id']),
        sa.ForeignKeyConstraint(['scheduled_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index(op.f('ix_subsidy_payouts_payout_id'), 'subsidy_payouts', ['payout_id'], unique=True)
    op.create_index(op.f('ix_subsidy_payouts_payout_datetime'), 'subsidy_payouts', ['payout_datetime'], unique=False)
    op.create_index(op.f('ix_subsidy_payouts_category_key'), 'subsidy_payouts', ['category_key'], unique=False)
    op.create_index(op.f('ix_subsidy_payouts_status'), 'subsidy_payouts', ['status'], unique=False)
    op.create_index(op.f('ix_subsidy_payouts_scheduled_by'), 'subsidy_payouts', ['scheduled_by'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_subsidy_payouts_scheduled_by'), table_name='subsidy_payouts')
    op.drop_index(op.f('ix_subsidy_payouts_status'), table_name='subsidy_payouts')
    op.drop_index(op.f('ix_subsidy_payouts_category_key'), table_name='subsidy_payouts')
    op.drop_index(op.f('ix_subsidy_payouts_payout_datetime'), table_name='subsidy_payouts')
    op.drop_index(op.f('ix_subsidy_payouts_payout_id'), table_name='subsidy_payouts')
    op.drop_table('subsidy_payouts')
