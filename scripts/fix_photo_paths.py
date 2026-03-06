#!/usr/bin/env python
"""Script to fix database paths - remove 'static/' prefix from shelter photo paths"""
import os
from app import create_app
from app.models import ShelterPhotos
from app.extensions import db

def fix_photo_paths():
    """Fix all shelter photo paths in the database"""
    
    app = create_app()
    with app.app_context():
        photos = ShelterPhotos.query.all()
        print(f"Found {len(photos)} photos to check/fix")
        
        fixed_count = 0
        for photo in photos:
            original_path = photo.photo_path
            
            # Check if path starts with 'static/'
            if original_path.startswith('static/'):
                # Remove the 'static/' prefix
                new_path = original_path[7:]  # Remove 'static/' (7 characters)
                photo.photo_path = new_path
                fixed_count += 1
                print(f"Fixed: '{original_path}' -> '{new_path}'")
                
                # Verify the file exists at the new path
                full_path = os.path.join(app.static_folder, new_path)
                if os.path.exists(full_path):
                    print(f"  [OK] File exists at: {full_path}")
                else:
                    print(f"  [WARN] File NOT found at: {full_path}")
        
        if fixed_count > 0:
            db.session.commit()
            print(f"\n[SUCCESS] Fixed {fixed_count} photo paths")
        else:
            print("\n[INFO] No paths needed fixing")

if __name__ == "__main__":
    fix_photo_paths()
