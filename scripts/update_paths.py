#!/usr/bin/env python
"""Direct database update to fix photo paths"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    try:
        # Direct SQL update
        from sqlalchemy import text
        result = db.session.execute(
            text("UPDATE shelter_photos SET photo_path = REPLACE(photo_path, 'static/', '')")
        )
        count = result.rowcount
        db.session.commit()
        
        print(f"SUCCESS: Updated {count} photo paths in database")
        
        # Verify
        from app.models import ShelterPhotos
        photos = ShelterPhotos.query.all()
        print(f"\nVerification - {len(photos)} photos now have:")
        for i, p in enumerate(photos[:3]):
            print(f"  {i+1}. {p.photo_path}")
            
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
