"""
Migration: Add CAL Documents Table
For Capital Assistance for Livelihood (CAL) program pre-approval documents
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
    """Create the cal_documents table"""
    conn = None
    try:
        print("Connecting to database...")
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Check if table already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'cal_documents'
            )
        """)
        
        if cursor.fetchone()[0]:
            print("Table 'cal_documents' already exists.")
        else:
            # Create the table
            print("Creating 'cal_documents' table...")
            cursor.execute("""
                CREATE TABLE cal_documents (
                    id SERIAL PRIMARY KEY,
                    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                    document_type VARCHAR(20) NOT NULL,
                    file_path VARCHAR(500) NOT NULL,
                    original_filename VARCHAR(255),
                    description TEXT,
                    verification_status VARCHAR(20) DEFAULT 'pending',
                    admin_notes TEXT,
                    verified_by INTEGER REFERENCES admin_users(id),
                    verified_at TIMESTAMP,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index on application_id for faster lookups
            cursor.execute("""
                CREATE INDEX idx_cal_documents_application_id ON cal_documents(application_id)
            """)
            
            # Create index on document_type
            cursor.execute("""
                CREATE INDEX idx_cal_documents_document_type ON cal_documents(document_type)
            """)
            
            conn.commit()
            print("✅ Successfully created 'cal_documents' table!")
            print("   - Columns: id, application_id, document_type, file_path, original_filename,")
            print("     description, verification_status, admin_notes, verified_by, verified_at, uploaded_at")
            print("   - Indexes created on application_id and document_type")
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == '__main__':
    run_migration()
