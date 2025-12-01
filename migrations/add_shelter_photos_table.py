"""
Migration script to add shelter_photos table for ESA program applications
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
    """Add shelter_photos table"""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if table already exists
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'shelter_photos' not in tables:
                print("Creating shelter_photos table...")
                db.session.execute(text('''
                    CREATE TABLE shelter_photos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        application_id INTEGER NOT NULL,
                        photo_path VARCHAR(255) NOT NULL,
                        caption VARCHAR(255),
                        uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        verified_by INTEGER,
                        verification_status VARCHAR(20) DEFAULT 'pending',
                        admin_notes TEXT,
                        FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
                        FOREIGN KEY (verified_by) REFERENCES users(id) ON DELETE SET NULL
                    )
                '''))
                
                # Create index for faster queries
                db.session.execute(text('''
                    CREATE INDEX idx_shelter_photos_application 
                    ON shelter_photos(application_id)
                '''))
                
                db.session.execute(text('''
                    CREATE INDEX idx_shelter_photos_status 
                    ON shelter_photos(verification_status)
                '''))
                
                db.session.commit()
                print("✓ shelter_photos table created successfully!")
                print("✓ Indexes created")
            else:
                print("✓ shelter_photos table already exists")
            
            # Create uploads directory
            uploads_dir = os.path.join('static', 'uploads', 'shelter_photos')
            if not os.path.exists(uploads_dir):
                os.makedirs(uploads_dir, exist_ok=True)
                print(f"✓ Created directory: {uploads_dir}")
            
            print("\n✅ Migration completed successfully!")
            print("ESA programs can now require shelter photo uploads.")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Migration failed: {e}")
            print("Please check your database configuration and try again.")
            raise

def downgrade():
    """Remove shelter_photos table (rollback)"""
    app = create_app()
    
    with app.app_context():
        try:
            print("Rolling back changes...")
            
            db.session.execute(text('DROP TABLE IF EXISTS shelter_photos'))
            db.session.commit()
            
            print("\n✅ Rollback completed successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Rollback failed: {e}")
            raise

if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("Shelter Photos Migration (ESA Programs)")
    print("=" * 60)
    
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        print("\n⚠️  WARNING: This will remove the shelter_photos table!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() == 'yes':
            downgrade()
        else:
            print("Rollback cancelled.")
    else:
        print("\nThis will add shelter_photos table for ESA program applications.")
        print("Community users will be able to upload shelter photos for verification.\n")
        upgrade()
