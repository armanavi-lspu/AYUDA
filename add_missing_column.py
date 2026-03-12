#!/usr/bin/env python
"""Quick migration: Add occupation_sector column to community_users"""

from app import create_app
from app.extensions import db
from sqlalchemy import text, inspect

app = create_app()

with app.app_context():
    try:
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('community_users')]
        
        if 'occupation_sector' not in columns:
            print("Adding occupation_sector column to community_users...")
            db.session.execute(text(
                'ALTER TABLE community_users ADD COLUMN occupation_sector VARCHAR(100) DEFAULT NULL'
            ))
            db.session.commit()
            print('✓ SUCCESS: Column added')
            
            # Verify it was added
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('community_users')]
            if 'occupation_sector' in columns:
                print('✓ VERIFIED: occupation_sector now exists in database')
            else:
                print('✗ ERROR: Column was not added successfully')
        else:
            print('✓ Column already exists, no action needed')
    except Exception as e:
        print(f'✗ ERROR: {e}')
        db.session.rollback()
