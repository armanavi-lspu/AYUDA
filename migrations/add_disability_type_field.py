"""
Migration: Add disability_type field to community_users table
"""
import sys
from pathlib import Path

def upgrade():
    """Add disability_type column to community_users table"""
    try:
        # Add parent directory to path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        
        from app import create_app, db
        from sqlalchemy import text
        app = create_app()
        with app.app_context():
            # Check if column already exists
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            columns = [column['name'] for column in inspector.get_columns('community_users')]
            
            if 'disability_type' not in columns:
                with db.engine.connect() as conn:
                    conn.execute(text("""
                        ALTER TABLE community_users
                        ADD COLUMN disability_type VARCHAR(100)
                    """))
                    conn.commit()
                    print("✓ Added disability_type column to community_users table")
            else:
                print("✓ disability_type column already exists")
                
    except Exception as e:
        print(f"Error during migration: {str(e)}")
        raise

if __name__ == '__main__':
    upgrade()
