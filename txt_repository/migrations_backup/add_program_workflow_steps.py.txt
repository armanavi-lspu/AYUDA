"""
Migration script to create program_workflow_steps table
Run this script to add the workflow steps table to the database
"""

import psycopg2
from psycopg2 import sql
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_db_connection():
    """Get database connection using config"""
    try:
        from config import Config
        # Parse DATABASE_URL
        db_url = Config.SQLALCHEMY_DATABASE_URI
        # postgresql://user:password@host:port/database
        if db_url.startswith('postgresql://'):
            db_url = db_url.replace('postgresql://', '')
        elif db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', '')
        
        # Parse credentials
        user_pass, host_db = db_url.split('@')
        user, password = user_pass.split(':')
        host_port, database = host_db.split('/')
        
        if ':' in host_port:
            host, port = host_port.split(':')
        else:
            host = host_port
            port = '5432'
        
        return psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise

def run_migration():
    """Create program_workflow_steps table"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if table already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'program_workflow_steps'
            );
        """)
        table_exists = cursor.fetchone()[0]
        
        if table_exists:
            print("Table 'program_workflow_steps' already exists. Skipping creation.")
        else:
            # Create the table
            cursor.execute("""
                CREATE TABLE program_workflow_steps (
                    id SERIAL PRIMARY KEY,
                    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
                    step_order INTEGER NOT NULL,
                    step_name VARCHAR(100) NOT NULL,
                    step_description TEXT,
                    step_type VARCHAR(50) NOT NULL DEFAULT 'approval',
                    is_pre_approval BOOLEAN DEFAULT FALSE,
                    requires_verification BOOLEAN DEFAULT TRUE,
                    min_items INTEGER DEFAULT 1,
                    allowed_file_types VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create index on program_id and step_order
            cursor.execute("""
                CREATE INDEX idx_workflow_steps_program 
                ON program_workflow_steps(program_id, step_order);
            """)
            
            print("Table 'program_workflow_steps' created successfully.")
        
        # Add default workflow steps for existing ESA programs
        cursor.execute("""
            SELECT id, program_type FROM programs WHERE program_type = 'ESA';
        """)
        esa_programs = cursor.fetchall()
        
        for program_id, _ in esa_programs:
            # Check if this program already has workflow steps
            cursor.execute("""
                SELECT COUNT(*) FROM program_workflow_steps WHERE program_id = %s;
            """, (program_id,))
            step_count = cursor.fetchone()[0]
            
            if step_count == 0:
                # Add default ESA workflow steps
                cursor.execute("""
                    INSERT INTO program_workflow_steps 
                    (program_id, step_order, step_name, step_description, step_type, is_pre_approval, requires_verification, min_items, allowed_file_types)
                    VALUES 
                    (%s, 1, 'Upload Shelter Photos', 'Upload at least 3 photos of your current shelter/housing situation', 'photo_upload', TRUE, TRUE, 3, 'jpg,jpeg,png,gif'),
                    (%s, 2, 'Submit Required Documents', 'Submit all required documents at MSWD Office', 'document_submission', FALSE, TRUE, 1, NULL),
                    (%s, 3, 'Schedule Release', 'Schedule your assistance release date', 'scheduling', FALSE, FALSE, 1, NULL);
                """, (program_id, program_id, program_id))
                print(f"Added default workflow steps for ESA program ID {program_id}")
        
        # Add default workflow steps for existing CA programs
        cursor.execute("""
            SELECT id, program_type FROM programs WHERE program_type = 'CA';
        """)
        cal_programs = cursor.fetchall()
        
        for program_id, _ in cal_programs:
            cursor.execute("""
                SELECT COUNT(*) FROM program_workflow_steps WHERE program_id = %s;
            """, (program_id,))
            step_count = cursor.fetchone()[0]
            
            if step_count == 0:
                # Add default CA workflow steps
                cursor.execute("""
                    INSERT INTO program_workflow_steps 
                    (program_id, step_order, step_name, step_description, step_type, is_pre_approval, requires_verification, min_items, allowed_file_types)
                    VALUES 
                    (%s, 1, 'Upload Certificate of Participation', 'Upload your Certificate of Participation from the livelihood training seminar', 'document_upload', TRUE, TRUE, 1, 'jpg,jpeg,png,pdf'),
                    (%s, 2, 'Upload Capital Assistance Proposal', 'Upload your business plan/proposal for the capital assistance', 'document_upload', TRUE, TRUE, 1, 'jpg,jpeg,png,pdf,doc,docx'),
                    (%s, 3, 'Submit Required Documents', 'Submit all required documents at MSWD Office', 'document_submission', FALSE, TRUE, 1, NULL),
                    (%s, 4, 'Schedule Release', 'Schedule your assistance release date', 'scheduling', FALSE, FALSE, 1, NULL);
                """, (program_id, program_id, program_id, program_id))
                print(f"Added default workflow steps for CA program ID {program_id}")
        
        # Add default workflow steps for other programs (AICS, 4Ps, etc.)
        cursor.execute("""
            SELECT id, program_type FROM programs WHERE program_type NOT IN ('ESA', 'CA');
        """)
        other_programs = cursor.fetchall()
        
        for program_id, program_type in other_programs:
            cursor.execute("""
                SELECT COUNT(*) FROM program_workflow_steps WHERE program_id = %s;
            """, (program_id,))
            step_count = cursor.fetchone()[0]
            
            if step_count == 0:
                # Add default workflow steps for other programs
                cursor.execute("""
                    INSERT INTO program_workflow_steps 
                    (program_id, step_order, step_name, step_description, step_type, is_pre_approval, requires_verification, min_items, allowed_file_types)
                    VALUES 
                    (%s, 1, 'Application Review', 'Wait for admin to review and approve your application', 'approval', TRUE, FALSE, 1, NULL),
                    (%s, 2, 'Submit Required Documents', 'Submit all required documents at MSWD Office', 'document_submission', FALSE, TRUE, 1, NULL),
                    (%s, 3, 'Schedule Release', 'Schedule your assistance release date', 'scheduling', FALSE, FALSE, 1, NULL);
                """, (program_id, program_id, program_id))
                print(f"Added default workflow steps for {program_type} program ID {program_id}")
        
        conn.commit()
        print("\nMigration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    run_migration()
