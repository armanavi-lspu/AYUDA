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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('assessments'):
        op.create_table(
            'assessments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('application_id', sa.Integer(), nullable=False),
            sa.Column('assessment_type', sa.String(length=50), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('scheduled_date', sa.DateTime(), nullable=True),
            sa.Column('scheduled_time', sa.String(length=10), nullable=True),
            sa.Column('location', sa.String(length=255), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='scheduled'),
            sa.Column('findings', sa.Text(), nullable=True),
            sa.Column('recommendations', sa.Text(), nullable=True),
            sa.Column('case_severity', sa.String(length=20), nullable=False, server_default='unrated'),
            sa.Column('severity_score', sa.Integer(), nullable=True),
            sa.Column('severity_factors', sa.Text(), nullable=True),
            sa.Column('severity_justification', sa.Text(), nullable=True),
            sa.Column('severity_updated_by', sa.Integer(), nullable=True),
            sa.Column('severity_updated_at', sa.DateTime(), nullable=True),
            sa.Column('conducted_by', sa.Integer(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
            sa.ForeignKeyConstraint(['conducted_by'], ['users.id']),
            sa.ForeignKeyConstraint(['severity_updated_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_application_id ON assessments (application_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_assessment_type ON assessments (assessment_type)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_scheduled_date ON assessments (scheduled_date)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_status ON assessments (status)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_case_severity ON assessments (case_severity)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_severity_score ON assessments (severity_score)")
        return

    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS case_severity VARCHAR(20)")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS severity_score INTEGER")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS severity_factors TEXT")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS severity_justification TEXT")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS severity_updated_by INTEGER")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS severity_updated_at TIMESTAMP WITHOUT TIME ZONE")

    op.execute("UPDATE assessments SET case_severity = 'unrated' WHERE case_severity IS NULL")
    op.execute("ALTER TABLE assessments ALTER COLUMN case_severity SET DEFAULT 'unrated'")
    op.execute("ALTER TABLE assessments ALTER COLUMN case_severity SET NOT NULL")

    op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_case_severity ON assessments (case_severity)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_assessments_severity_score ON assessments (severity_score)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_assessments_severity_updated_by_users'
            ) THEN
                ALTER TABLE assessments
                ADD CONSTRAINT fk_assessments_severity_updated_by_users
                FOREIGN KEY (severity_updated_by) REFERENCES users (id);
            END IF;
        END$$;
        """
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('assessments'):
        return

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_assessments_severity_updated_by_users'
            ) THEN
                ALTER TABLE assessments DROP CONSTRAINT fk_assessments_severity_updated_by_users;
            END IF;
        END$$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_assessments_severity_score")
    op.execute("DROP INDEX IF EXISTS ix_assessments_case_severity")
    op.execute("ALTER TABLE assessments DROP COLUMN IF EXISTS severity_updated_at")
    op.execute("ALTER TABLE assessments DROP COLUMN IF EXISTS severity_updated_by")
    op.execute("ALTER TABLE assessments DROP COLUMN IF EXISTS severity_justification")
    op.execute("ALTER TABLE assessments DROP COLUMN IF EXISTS severity_factors")
    op.execute("ALTER TABLE assessments DROP COLUMN IF EXISTS severity_score")
    op.execute("ALTER TABLE assessments DROP COLUMN IF EXISTS case_severity")
