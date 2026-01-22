"""
Quick check if migration worked
"""
from app import create_app
from app.models import User
from app.extensions import db

app = create_app()

with app.app_context():
    # Check if column exists by trying to access it
    try:
        user = User.query.first()
        if user:
            print(f"✅ Migration successful!")
            print(f"   User: {user.email}")
            print(f"   profile_complete_alert_dismissed: {user.profile_complete_alert_dismissed}")
        else:
            print("No users in database")
    except Exception as e:
        print(f"❌ Error: {e}")
