"""
Migration script to add allow_online_upload column to programs table.
This column controls whether applicants can upload documents online for this program.
"""

import psycopg2
from psycopg2 import sql

# Database connection settings
DB_CONFIG = {
    'host': 'localhost',
    'database': 'Ayuda',
    'user': 'postgres',
    'password': '011523'
}

def run_migration():
    """Add allow_online_upload column to programs table"""
    conn = None
    try:
        print("Connecting to database...")
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'programs' AND column_name = 'allow_online_upload'
        """)
        
        if cursor.fetchone():
            print("Column 'allow_online_upload' already exists in programs table.")
        else:
            # Add the column with default value TRUE (enabled by default)
            print("Adding 'allow_online_upload' column to programs table...")
            cursor.execute("""
                ALTER TABLE programs 
                ADD COLUMN allow_online_upload BOOLEAN DEFAULT TRUE
            """)
            
            # Update existing programs to have online upload enabled
            cursor.execute("""
                UPDATE programs 
                SET allow_online_upload = TRUE 
                WHERE allow_online_upload IS NULL
            """)
            
            conn.commit()
            print("✅ Successfully added 'allow_online_upload' column to programs table!")
            print("   - Default value: TRUE (online upload enabled)")
            print("   - All existing programs now have online upload enabled")
        
        # Verify the column
        cursor.execute("""
            SELECT COUNT(*) FROM programs
        """)
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM programs WHERE allow_online_upload = TRUE
        """)
        enabled = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM programs WHERE allow_online_upload = FALSE
        """)
        disabled = cursor.fetchone()[0]
        
        print(f"\nProgram Statistics:")
        print(f"   - Total programs: {total}")
        print(f"   - Online upload enabled: {enabled}")
        print(f"   - Online upload disabled: {disabled}")
        
        cursor.close()
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
            print("\nDatabase connection closed.")

if __name__ == '__main__':
    print("=" * 60)
    print("Migration: Add allow_online_upload to programs table")
    print("=" * 60)
    run_migration()
    print("\n✅ Migration completed!")
