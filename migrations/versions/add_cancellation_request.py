"""Add cancellation request fields to applications

Revision ID: add_cancellation_request
Revises: 936217dd0e15
Create Date: 2026-03-10 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_cancellation_request'
down_revision = '936217dd0e15'
branch_labels = None
depends_on = None


def upgrade():
    # Keep this migration idempotent-friendly for databases that may already
    # contain some cancellation columns due to prior manual/schema drift.
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cancellation_requested BOOLEAN")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cancellation_reason TEXT")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cancellation_requested_at TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cancellation_status VARCHAR(20)")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cancellation_reviewed_by INTEGER")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cancellation_reviewed_at TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cancellation_admin_notes TEXT")

    op.execute("UPDATE applications SET cancellation_requested = FALSE WHERE cancellation_requested IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_applications_cancellation_requested ON applications (cancellation_requested)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_applications_cancellation_status ON applications (cancellation_status)")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'applications_cancellation_reviewed_by_fkey'
            ) THEN
                ALTER TABLE applications
                ADD CONSTRAINT applications_cancellation_reviewed_by_fkey
                FOREIGN KEY (cancellation_reviewed_by) REFERENCES users (id);
            END IF;
        END$$;
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_applications_cancellation_status")
    op.execute("DROP INDEX IF EXISTS ix_applications_cancellation_requested")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'applications_cancellation_reviewed_by_fkey'
            ) THEN
                ALTER TABLE applications DROP CONSTRAINT applications_cancellation_reviewed_by_fkey;
            END IF;
        END$$;
        """
    )

    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cancellation_admin_notes")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cancellation_reviewed_at")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cancellation_reviewed_by")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cancellation_status")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cancellation_requested_at")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cancellation_reason")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cancellation_requested")