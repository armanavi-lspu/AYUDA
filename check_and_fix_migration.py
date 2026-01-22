"""
Check if column exists and create it if needed
"""
import psycopg2
from config import Config

def check_and_fix():
    try:
        conn = psycopg2.connect(Config.SQLALCHEMY_DATABASE_URI)
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' 
            AND column_name = 'profile_complete_alert_dismissed';
        """)
        result = cursor.fetchone()
        
        if result:
            print("✅ Column already exists!")
        else:
            print("❌ Column does not exist. Creating it now...")
            
            # Add the column
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN profile_complete_alert_dismissed BOOLEAN DEFAULT FALSE;
            """)
            
            # Update existing users
            cursor.execute("""
                UPDATE users 
                SET profile_complete_alert_dismissed = FALSE 
                WHERE profile_complete_alert_dismissed IS NULL;
            """)
            
            conn.commit()
            print("✅ Column created successfully!")
            
            # Verify
            cursor.execute("""
                SELECT column_name, data_type, column_default 
                FROM information_schema.columns 
                WHERE table_name = 'users' 
                AND column_name = 'profile_complete_alert_dismissed';
            """)
            result = cursor.fetchone()
            
            if result:
                print(f"\n✓ Verification successful:")
                print(f"  Column name: {result[0]}")
                print(f"  Data type: {result[1]}")
                print(f"  Default value: {result[2]}")
            
            # Test query
            cursor.execute("SELECT id, email, profile_complete_alert_dismissed FROM users LIMIT 2;")
            users = cursor.fetchall()
            print(f"\n📊 Sample data:")
            for user in users:
                print(f"  User {user[0]}: {user[1]} - Dismissed: {user[2]}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()

if __name__ == '__main__':
    check_and_fix()
