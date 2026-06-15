"""
Migration: Add Assessment Tables
For SCSR assessments (interviews, home visits) aligned with MSWD standard practices.
"""

import os
import psycopg2

# Database connection settings
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'database': os.environ.get('DB_NAME', 'Ayuda'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', ''),
}


def run_migration():
    """Create the assessments and assessment_documents tables"""
    conn = None
    try:
        print("Connecting to database...")
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # --- assessments table ---
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'assessments'
            )
        """)
        if cursor.fetchone()[0]:
            print("Table 'assessments' already exists.")
        else:
            print("Creating 'assessments' table...")
            cursor.execute("""
                CREATE TABLE assessments (
                    id SERIAL PRIMARY KEY,
                    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                    assessment_type VARCHAR(50) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    scheduled_date TIMESTAMP,
                    scheduled_time VARCHAR(10),
                    location VARCHAR(255),
                    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
                    findings TEXT,
                    recommendations TEXT,
                    conducted_by INTEGER NOT NULL REFERENCES users(id),
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX idx_assessments_application_id ON assessments(application_id)")
            cursor.execute("CREATE INDEX idx_assessments_type ON assessments(assessment_type)")
            cursor.execute("CREATE INDEX idx_assessments_status ON assessments(status)")
            cursor.execute("CREATE INDEX idx_assessments_scheduled_date ON assessments(scheduled_date)")
            print("  ✅ 'assessments' table created.")

        # --- assessment_documents table ---
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'assessment_documents'
            )
        """)
        if cursor.fetchone()[0]:
            print("Table 'assessment_documents' already exists.")
        else:
            print("Creating 'assessment_documents' table...")
            cursor.execute("""
                CREATE TABLE assessment_documents (
                    id SERIAL PRIMARY KEY,
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    file_path VARCHAR(255) NOT NULL,
                    original_filename VARCHAR(255) NOT NULL,
                    file_size INTEGER,
                    file_type VARCHAR(100),
                    description TEXT,
                    uploaded_by INTEGER NOT NULL REFERENCES users(id),
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX idx_assessment_documents_assessment_id ON assessment_documents(assessment_id)")
            print("  ✅ 'assessment_documents' table created.")

        conn.commit()
        print("\n✅ Migration complete!")

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
