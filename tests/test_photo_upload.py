#!/usr/bin/env python
"""Test script to upload and view photos"""
import requests
import os
from pathlib import Path
import shutil

# Flask server URL
BASE_URL = "http://127.0.0.1:5000"

# Session to maintain cookies
session = requests.Session()

# Test user credentials (adjust as needed based on your app)
test_user_email = "test@example.com"
test_user_password = "password123"

def test_photo_upload():
    """Test the photo upload and view functionality"""
    
    print("=" * 60)
    print("PHOTO UPLOAD & VIEW TEST")
    print("=" * 60)
    
    # Step 1: Use an existing test image
    test_image_path = "static/images/hero-bg.jpg"
    
    if not os.path.exists(test_image_path):
        print(f"[FAIL] Test image not found at {test_image_path}")
        return False
    
    print(f"\n[OK] Found test image: {test_image_path}")
    print(f"     File size: {os.path.getsize(test_image_path)} bytes")
    
    # Step 2: Check if uploaded photos directory exists
    upload_dir = "static/uploads/shelter_photos"
    if os.path.exists(upload_dir):
        print(f"\n[OK] Upload directory exists: {upload_dir}")
        
        # List existing photos
        for app_id in os.listdir(upload_dir):
            app_path = os.path.join(upload_dir, app_id)
            if os.path.isdir(app_path):
                photos = os.listdir(app_path)
                if photos:
                    print(f"\n     Application {app_id} has {len(photos)} photos:")
                    for photo in photos[:3]:  # Show first 3
                        photo_path = os.path.join(app_path, photo)
                        file_size = os.path.getsize(photo_path)
                        print(f"       - {photo} ({file_size} bytes)")
                        
                        # Test if the static file can be accessed
                        static_url = f"/static/uploads/shelter_photos/{app_id}/{photo}"
                        try:
                            response = session.get(f"{BASE_URL}{static_url}", timeout=5)
                            if response.status_code == 200:
                                print(f"         [OK] Accessible via URL: {static_url}")
                            else:
                                print(f"         [FAIL] Got status {response.status_code} for {static_url}")
                        except Exception as e:
                            print(f"         [ERROR] accessing photo: {str(e)}")
    else:
        print(f"[FAIL] Upload directory not found: {upload_dir}")
    
    # Step 3: Check application database to see shelter photos
    print("\n" + "-" * 60)
    print("Checking database for shelter photos...")
    print("-" * 60)
    
    try:
        from app import create_app
        from app.models import ShelterPhotos
        
        app = create_app()
        with app.app_context():
            # Get all photos
            photos = ShelterPhotos.query.all()
            print(f"\nTotal photos in database: {len(photos)}")
            
            # Group by application
            photos_by_app = {}
            for photo in photos:
                app_id = photo.application_id
                if app_id not in photos_by_app:
                    photos_by_app[app_id] = []
                photos_by_app[app_id].append(photo)
            
            # Display summary
            for app_id in sorted(photos_by_app.keys())[:5]:
                app_photos = photos_by_app[app_id]
                print(f"\n     Application {app_id}:")
                for p in app_photos:
                    print(f"       - Database path: {p.photo_path}")
                    print(f"         Uploaded: {p.uploaded_at}")
                    
                    # Construct full path for verification
                    full_path = os.path.join(app.static_folder, p.photo_path)
                    
                    # Check if file exists
                    if os.path.exists(full_path):
                        file_size = os.path.getsize(full_path)
                        print(f"         [OK] File exists ({file_size} bytes)")
                    else:
                        print(f"         [FAIL] File NOT found: {full_path}")
                    
                    # Test URL accessibility
                    static_url = f"/static/{p.photo_path}"
                    try:
                        response = session.head(f"{BASE_URL}{static_url}", timeout=5)
                        if response.status_code == 200:
                            print(f"         [OK] Accessible via URL: {static_url}")
                        else:
                            print(f"         [WARN] Status {response.status_code} for URL: {static_url}")
                    except Exception as e:
                        print(f"         [ERROR] URL error: {str(e)}")
    
    except Exception as e:
        print(f"[ERROR] accessing database: {str(e)}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("\nNotes:")
    print("- Check the Flask server console for any errors")
    print("- Verify photos display correctly in browser at http://127.0.0.1:5000")
    print("- Check browser network tab for 404 errors on photo URLs")

if __name__ == "__main__":
    test_photo_upload()
