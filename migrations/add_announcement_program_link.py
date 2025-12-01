"""
Migration script to add program_id and attachment_url fields to announcements table
Run this script to update your database schema
"""

import sys
import os

# Add the parent directory to the path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from sqlalchemy import text

def upgrade():
    """Add new columns to announcements table"""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if columns already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('announcements')]
            
            # Add program_id column if it doesn't exist
            if 'program_id' not in columns:
                print("Adding program_id column...")
                db.session.execute(text('''
                    ALTER TABLE announcements 
                    ADD COLUMN program_id INTEGER NULL
                '''))
                print("✓ program_id column added")
            else:
                print("✓ program_id column already exists")
            
            # Add attachment_url column if it doesn't exist
            if 'attachment_url' not in columns:
                print("Adding attachment_url column...")
                db.session.execute(text('''
                    ALTER TABLE announcements 
                    ADD COLUMN attachment_url VARCHAR(500) NULL
                '''))
                print("✓ attachment_url column added")
            else:
                print("✓ attachment_url column already exists")
            
            # Add foreign key constraint for program_id
            if 'program_id' not in columns:
                print("Adding foreign key constraint...")
                try:
                    db.session.execute(text('''
                        ALTER TABLE announcements 
                        ADD CONSTRAINT fk_announcements_program 
                        FOREIGN KEY (program_id) REFERENCES programs(id) 
                        ON DELETE SET NULL
                    '''))
                    print("✓ Foreign key constraint added")
                except Exception as e:
                    print(f"Note: Foreign key constraint may already exist or not supported: {e}")
            
            db.session.commit()
            print("\n✅ Migration completed successfully!")
            print("You can now link announcements to programs and add attachment URLs.")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Migration failed: {e}")
            print("Please check your database configuration and try again.")
            raise

def downgrade():
    """Remove the added columns (rollback)"""
    app = create_app()
    
    with app.app_context():
        try:
            print("Rolling back changes...")
            
            # Drop foreign key constraint first (if exists)
            try:
                db.session.execute(text('''
                    ALTER TABLE announcements 
                    DROP CONSTRAINT IF EXISTS fk_announcements_program
                '''))
            except Exception as e:
                print(f"Note: Could not drop foreign key constraint: {e}")
            
            # Drop columns
            db.session.execute(text('''
                ALTER TABLE announcements 
                DROP COLUMN IF EXISTS program_id,
                DROP COLUMN IF EXISTS attachment_url
            '''))
            
            db.session.commit()
            print("\n✅ Rollback completed successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Rollback failed: {e}")
            raise

if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("Announcement Program Link Migration")
    print("=" * 60)
    
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        print("\n⚠️  WARNING: This will remove program_id and attachment_url columns!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() == 'yes':
            downgrade()
        else:
            print("Rollback cancelled.")
    else:
        print("\nThis will add program_id and attachment_url columns to announcements table.")
        print("This allows linking announcements to programs for easy application access.\n")
        upgrade()
