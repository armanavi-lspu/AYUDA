"""
Run database migration for verification status fields
"""
from app import create_app
from app.extensions import db
from sqlalchemy import text

def run_migration():
    """Execute the verification fields migration using Flask-SQLAlchemy"""
    
    app = create_app()
    
    with app.app_context():
        try:
            print("=" * 60)
            print("Verification Status Fields Migration")
            print("=" * 60)
            print()
            
            # Read migration SQL file
            with open('migrations/add_verification_status_fields.sql', 'r', encoding='utf-8') as f:
                migration_sql = f.read()
            
            print("Running migration...")
            
            # Execute migration
            db.session.execute(text(migration_sql))
            db.session.commit()
            
            print("✅ Migration completed successfully!")
            
            # Verify columns exist
            print("\nVerifying migration...")
            
            # Check if verification columns exist
            verification_columns = [
                'senior_citizen_verification',
                'pwd_verification', 
                'solo_parent_verification'
            ]
            
            for column in verification_columns:
                result = db.session.execute(text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='community_users' AND column_name='{column}'
                """))
                if result.fetchone():
                    print(f"✅ Column '{column}' added to community_users table")
                else:
                    print(f"❌ Column '{column}' not found")
            
            print("\n✅ Migration verification completed!")
            
        except Exception as e:
            print(f"❌ Migration failed: {str(e)}")
            db.session.rollback()
            return False
    
    return True

if __name__ == '__main__':
    print("Starting verification fields migration...")
    success = run_migration()
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed!")