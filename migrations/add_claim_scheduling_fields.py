"""
Migration: Add claim scheduling fields to applications table
Run this to add the new claim scheduling functionality fields.

Execute with: python migrations/add_claim_scheduling_fields.py
"""

import sys
import os

# Add the parent directory to the path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text

def upgrade():
    """Add claim scheduling fields to applications table"""
    
    app = create_app()
    
    with app.app_context():
        try:
            print("Adding claim scheduling fields to applications table...")
            
            # Add new columns for claim scheduling
            db.session.execute(text("""
                ALTER TABLE applications 
                ADD COLUMN IF NOT EXISTS claim_date TIMESTAMP
            """))
            
            db.session.execute(text("""
                ALTER TABLE applications 
                ADD COLUMN IF NOT EXISTS claim_time VARCHAR(10)
            """))
            
            db.session.execute(text("""
                ALTER TABLE applications 
                ADD COLUMN IF NOT EXISTS claim_location VARCHAR(255)
            """))
            
            db.session.execute(text("""
                ALTER TABLE applications 
                ADD COLUMN IF NOT EXISTS claim_instructions TEXT
            """))
            
            db.session.execute(text("""
                ALTER TABLE applications 
                ADD COLUMN IF NOT EXISTS claim_status VARCHAR(20) DEFAULT 'not_scheduled'
            """))
            
            db.session.execute(text("""
                ALTER TABLE applications 
                ADD COLUMN IF NOT EXISTS claim_scheduled_by INTEGER REFERENCES users(id)
            """))
            
            db.session.execute(text("""
                ALTER TABLE applications 
                ADD COLUMN IF NOT EXISTS claim_scheduled_at TIMESTAMP
            """))
            
            # Add indexes for better performance
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_app_claim_date ON applications(claim_date)
            """))
            
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_app_claim_status ON applications(claim_status)
            """))
            
            db.session.commit()
            print("✅ Successfully added claim scheduling fields to applications table")
            print("\nNew fields added:")
            print("  - claim_date: Scheduled date for claiming assistance")
            print("  - claim_time: Time slot (e.g., '09:00 AM', '02:00 PM')")
            print("  - claim_location: Location for claiming (office address, etc.)")
            print("  - claim_instructions: Special instructions for claiming")
            print("  - claim_status: not_scheduled, scheduled, claimed, missed")
            print("  - claim_scheduled_by: Admin who scheduled (foreign key)")
            print("  - claim_scheduled_at: When the claim was scheduled")
            print("\nIndexes added:")
            print("  - idx_app_claim_date")
            print("  - idx_app_claim_status")
            
        except Exception as e:
            print(f"❌ Error during migration: {e}")
            db.session.rollback()
            return False
            
    return True

def downgrade():
    """Remove claim scheduling fields from applications table"""
    
    app = create_app()
    
    with app.app_context():
        try:
            print("Removing claim scheduling fields from applications table...")
            
            # Drop indexes first
            db.session.execute(text("DROP INDEX IF EXISTS idx_app_claim_status"))
            db.session.execute(text("DROP INDEX IF EXISTS idx_app_claim_date"))
            
            # Remove columns
            columns_to_drop = [
                'claim_scheduled_at',
                'claim_scheduled_by', 
                'claim_status',
                'claim_instructions',
                'claim_location',
                'claim_time',
                'claim_date'
            ]
            
            for column in columns_to_drop:
                db.session.execute(text(f"ALTER TABLE applications DROP COLUMN IF EXISTS {column}"))
            
            db.session.commit()
            print("✅ Successfully removed claim scheduling fields from applications table")
            
        except Exception as e:
            print(f"❌ Error during downgrade: {e}")
            db.session.rollback()
            return False
            
    return True

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        success = downgrade()
    else:
        success = upgrade()
    
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed!")
        sys.exit(1)