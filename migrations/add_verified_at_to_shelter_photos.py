"""
Migration: Add verified_at column to ShelterPhotos table

This migration adds the verified_at column to track when 
shelter photos were verified by admin.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

def upgrade():
    """Add verified_at column to shelter_photos table"""
    app = create_app()
    with app.app_context():
        try:
            # Add verified_at column
            db.engine.execute("""
                ALTER TABLE shelter_photos 
                ADD COLUMN verified_at DATETIME
            """)
            
            print("✓ Added verified_at column to shelter_photos table")
            return True
            
        except Exception as e:
            print(f"✗ Error adding verified_at column: {str(e)}")
            return False

def downgrade():
    """Remove verified_at column from shelter_photos table"""
    app = create_app()
    with app.app_context():
        try:
            # Remove verified_at column
            db.engine.execute("""
                ALTER TABLE shelter_photos 
                DROP COLUMN verified_at
            """)
            
            print("✓ Removed verified_at column from shelter_photos table")
            return True
            
        except Exception as e:
            print(f"✗ Error removing verified_at column: {str(e)}")
            return False

if __name__ == '__main__':
    print("Running migration: Add verified_at to ShelterPhotos")
    success = upgrade()
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed!")