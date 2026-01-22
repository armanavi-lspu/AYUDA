"""
Run database migration for document upload workflow using Flask-SQLAlchemy
"""
from app import create_app
from app.extensions import db
from sqlalchemy import text

def run_migration():
    """Execute the migration using Flask-SQLAlchemy"""
    
    app = create_app()
    
    with app.app_context():
        try:
            print("=" * 60)
            print("Document Upload Workflow Migration")
            print("=" * 60)
            print()
            
            # Read migration SQL file
            with open('migrations/add_document_upload_workflow_postgresql.sql', 'r', encoding='utf-8') as f:
                migration_sql = f.read()
            
            print("Running migration...")
            
            # Execute migration
            db.session.execute(text(migration_sql))
            db.session.commit()
            
            print("✅ Migration completed successfully!")
            
            # Verify tables and columns exist
            print("\nVerifying migration...")
            
            # Check if column exists
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='applications' AND column_name='document_upload_status'
            """))
            if result.fetchone():
                print("✅ Column 'document_upload_status' added to applications table")
            else:
                print("❌ Column 'document_upload_status' not found")
            
            # Check if table exists
            result = db.session.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name='application_document_uploads'
            """))
            if result.fetchone():
                print("✅ Table 'application_document_uploads' created")
            else:
                print("❌ Table 'application_document_uploads' not found")
            
            # Check indexes
            result = db.session.execute(text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename='application_document_uploads'
            """))
            indexes = result.fetchall()
            print(f"✅ Created {len(indexes)} indexes on application_document_uploads table")
            
            print("\n✨ Migration completed successfully!")
            print("\n" + "=" * 60)
            print("Next Steps:")
            print("=" * 60)
            print("1. Restart your Flask application (Ctrl+C and python main.py)")
            print("2. Test the document upload feature:")
            print("   - Submit a new application as a community user")
            print("   - Upload documents")
            print("   - Review as admin")
            print("3. Check logs for any errors")
            print("\nFor more information, see:")
            print("- DOCUMENT_UPLOAD_WORKFLOW.md")
            print("- QUICK_START_DOCUMENT_UPLOAD.md")
            
            return True
            
        except Exception as e:
            print(f"❌ Error running migration: {e}")
            db.session.rollback()
            print("\nIf needed, you can rollback using the SQL at the end of:")
            print("migrations/add_document_upload_workflow_postgresql.sql")
            return False

if __name__ == '__main__':
    run_migration()
