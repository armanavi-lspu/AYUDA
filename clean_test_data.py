#!/usr/bin/env python
"""Clean test data to prepare for regeneration with new migration"""

from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    connection = db.engine.connect()
    
    try:
        # Delete test applications
        print("🗑️  Deleting test applications...")
        delete_apps = text("DELETE FROM applications WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'user%@test.com')")
        connection.execute(delete_apps)
        connection.commit()
        print("✅ Deleted test applications")
        
        # Delete test users
        print("🗑️  Deleting test users...")
        delete_users = text("DELETE FROM community_users WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'user%@test.com')")
        connection.execute(delete_users)
        connection.commit()
        print("✅ Deleted test community profiles")
        
        delete_users = text("DELETE FROM users WHERE email LIKE 'user%@test.com'")
        connection.execute(delete_users)
        connection.commit()
        print("✅ Deleted test users")
        
        print("\n🎯 Test data cleaned successfully!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        connection.rollback()
    finally:
        connection.close()
