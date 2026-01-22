"""
Verify the migration was successful
"""
import psycopg2
from config import Config

def verify_migration():
    """Verify the column was added"""
    try:
        conn = psycopg2.connect(Config.SQLALCHEMY_DATABASE_URI)
        cursor = conn.cursor()
        
        print("Verifying migration...\n")
        
        # Check if column exists
        cursor.execute("""
            SELECT column_name, data_type, column_default 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'profile_complete_alert_dismissed';
        """)
        result = cursor.fetchone()
        
        if result:
            print(f"✅ Column found in users table:")
            print(f"   Name: {result[0]}")
            print(f"   Type: {result[1]}")
            print(f"   Default: {result[2]}")
        else:
            print("❌ Column not found!")
        
        # Check sample data
        cursor.execute("""
            SELECT id, email, profile_complete_alert_dismissed 
            FROM users 
            LIMIT 3;
        """)
        users = cursor.fetchall()
        
        print(f"\n📊 Sample data from users table:")
        for user in users:
            print(f"   User ID {user[0]}: {user[1]} - Dismissed: {user[2]}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    verify_migration()
