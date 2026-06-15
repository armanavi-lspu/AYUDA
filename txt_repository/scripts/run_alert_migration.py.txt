"""
Run migration to add profile_complete_alert_dismissed column
"""
import psycopg2
from config import Config

def run_migration():
    """Execute the migration SQL file"""
    try:
        # Connect to database
        conn = psycopg2.connect(Config.SQLALCHEMY_DATABASE_URI)
        cursor = conn.cursor()
        
        print("Connected to database successfully!")
        
        # Read and execute migration file
        with open('migrations/add_profile_complete_alert_dismissed.sql', 'r') as f:
            sql = f.read()
        
        # Execute each statement
        statements = sql.split(';')
        for statement in statements:
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                cursor.execute(statement)
                print(f"✓ Executed: {statement[:50]}...")
        
        # Commit changes
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
        # Verify the column was added
        cursor.execute("""
            SELECT column_name, data_type, column_default 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'profile_complete_alert_dismissed';
        """)
        result = cursor.fetchone()
        
        if result:
            print(f"\n✓ Verification: Column '{result[0]}' added successfully")
            print(f"  Type: {result[1]}")
            print(f"  Default: {result[2]}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ Error running migration: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False
    
    return True

if __name__ == '__main__':
    run_migration()
