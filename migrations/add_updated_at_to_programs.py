"""
Migration: Add updated_at field to programs table
Created: February 8, 2026
Purpose: Track when programs were last modified for admin viewing
"""
import os
import psycopg2
from datetime import datetime

def migrate_add_updated_at_to_programs():
    """Add updated_at column to programs table"""
    
    try:
        # Connect to PostgreSQL database using environment variables
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            database=os.environ.get('DB_NAME', 'Ayuda'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', '')
        )
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='programs' AND column_name='updated_at'
        """)
        exists = cursor.fetchone()
        
        if not exists:
            print("📝 Adding updated_at column to programs table...")
            
            # Add the updated_at column
            cursor.execute("""
                ALTER TABLE programs 
                ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """)
            
            # Set initial updated_at value to current date for existing programs
            cursor.execute("""
                UPDATE programs 
                SET updated_at = CURRENT_TIMESTAMP
                WHERE updated_at IS NULL
            """)
            
            # Commit changes
            conn.commit()
            print("✅ Successfully added updated_at column to programs table")
            print(f"📅 Set initial updated_at to current timestamp")
            
        else:
            print("ℹ️ Column 'updated_at' already exists in programs table")
            
        # Close connection
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error during migration: {str(e)}")
        if 'conn' in locals():
            conn.close()
        return False

if __name__ == "__main__":
    print("🚀 Running migration: Add updated_at to programs table")
    success = migrate_add_updated_at_to_programs()
    
    if success:
        print("🎉 Migration completed successfully!")
    else:
        print("💥 Migration failed!")