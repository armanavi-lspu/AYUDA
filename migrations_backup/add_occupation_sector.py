"""
Database migration: Add occupation_sector column to community_users.

Run inside a Flask app context:
    flask shell
    >>> exec(open('migrations_backup/add_occupation_sector.py').read())

Or via:
    python -c "from app import create_app; app = create_app(); exec(open('migrations_backup/add_occupation_sector.py').read())"
"""

from app.extensions import db
from sqlalchemy import text, inspect


def run_migration():
    """Add occupation_sector column and index to community_users if missing."""
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('community_users')]

    if 'occupation_sector' not in columns:
        db.session.execute(text(
            'ALTER TABLE community_users ADD COLUMN occupation_sector VARCHAR(100)'
        ))
        db.session.execute(text(
            'CREATE INDEX IF NOT EXISTS idx_occupation_sector ON community_users(occupation_sector)'
        ))
        db.session.commit()
        print('SUCCESS: Added occupation_sector column to community_users')
    else:
        print('SKIP: occupation_sector column already exists')


if __name__ != '__main__':
    # When exec'd inside a Flask app context
    run_migration()
