"""
Run database migration for document upload workflow
"""
import psycopg2
import os

def run_migration():
    """Execute the PostgreSQL migration"""
    
    # Database connection parameters (from config.py)
    DB_HOST = 'localhost'
    DB_NAME = 'Ayuda'
    DB_USER = 'postgres'
    DB_PASSWORD = '011523'
    
    # Read migration SQL file
    migration_file = 'migrations/add_document_upload_workflow_postgresql.sql'
    
    if not os.path.exists(migration_file):
        print(f"Error: Migration file not found: {migration_file}")
        return False
    
    with open(migration_file, 'r', encoding='utf-8') as f:
        migration_sql = f.read()
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        conn.autocommit = False  # Use transaction
        cursor = conn.cursor()
        
        print("Running migration...")
        
        # Execute migration
        cursor.execute(migration_sql)
        
        # Commit transaction
        conn.commit()
        print("✅ Migration completed successfully!")
        
        # Verify tables and columns exist
        print("\nVerifying migration...")
        
        # Check if column exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='applications' AND column_name='document_upload_status'
        """)
        if cursor.fetchone():
            print("✅ Column 'document_upload_status' added to applications table")
        else:
            print("❌ Column 'document_upload_status' not found")
        
        # Check if table exists
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_name='application_document_uploads'
        """)
        if cursor.fetchone():
            print("✅ Table 'application_document_uploads' created")
        else:
            print("❌ Table 'application_document_uploads' not found")
        
        # Check indexes
        cursor.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename='application_document_uploads'
        """)
        indexes = cursor.fetchall()
        print(f"✅ Created {len(indexes)} indexes on application_document_uploads table")
        
        cursor.close()
        conn.close()
        
        print("\n✨ Migration completed successfully! You can now run the application.")
        return True
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("Document Upload Workflow Migration")
    print("=" * 60)
    print()
    
    success = run_migration()
    
    if success:
        print("\n" + "=" * 60)
        print("Next Steps:")
        print("=" * 60)
        print("1. Restart your Flask application")
        print("2. Test the document upload feature:")
        print("   - Submit a new application as a community user")
        print("   - Upload documents")
        print("   - Review as admin")
        print("3. Check logs for any errors")
        print("\nFor more information, see:")
        print("- DOCUMENT_UPLOAD_WORKFLOW.md")
        print("- QUICK_START_DOCUMENT_UPLOAD.md")
    else:
        print("\n❌ Migration failed. Please check the errors above.")
        print("If needed, you can rollback using the SQL at the end of the migration file.")
