"""
Migration: Add verification code fields to applications table
"""
import sys
from pathlib import Path

def upgrade():
    """Add verification_code and related fields to applications table"""
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
            columns = [column['name'] for column in inspector.get_columns('applications')]
            
            with db.engine.connect() as conn:
                if 'verification_code' not in columns:
                    conn.execute(text("""
                        ALTER TABLE applications
                        ADD COLUMN verification_code VARCHAR(20) UNIQUE
                    """))
                    conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS idx_verification_code 
                        ON applications(verification_code)
                    """))
                    print("✓ Added verification_code column")
                
                if 'code_generated_at' not in columns:
                    conn.execute(text("""
                        ALTER TABLE applications
                        ADD COLUMN code_generated_at TIMESTAMP
                    """))
                    print("✓ Added code_generated_at column")
                
                if 'code_used_at' not in columns:
                    conn.execute(text("""
                        ALTER TABLE applications
                        ADD COLUMN code_used_at TIMESTAMP
                    """))
                    print("✓ Added code_used_at column")
                
                if 'documents_submitted_at' not in columns:
                    conn.execute(text("""
                        ALTER TABLE applications
                        ADD COLUMN documents_submitted_at TIMESTAMP
                    """))
                    print("✓ Added documents_submitted_at column")
                
                conn.commit()
                print("✅ Migration completed successfully!")
                
    except Exception as e:
        print(f"❌ Error during migration: {str(e)}")
        raise

if __name__ == '__main__':
    upgrade()
