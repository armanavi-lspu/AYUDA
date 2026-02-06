"""
Add ApplicationWorkflowStatus table for tracking workflow step progress
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extensions import db

def upgrade():
    """Add application_workflow_status table"""
    from sqlalchemy import text
    
    with db.engine.connect() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS application_workflow_status (
                id SERIAL PRIMARY KEY,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                workflow_step_id INTEGER NOT NULL REFERENCES program_workflow_steps(id) ON DELETE CASCADE,
                step_status VARCHAR(20) NOT NULL DEFAULT 'not_started',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                reviewed_at TIMESTAMP,
                reviewed_by INTEGER REFERENCES users(id),
                admin_feedback TEXT,
                step_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(application_id, workflow_step_id)
            );
        '''))
        
        conn.execute(text('''
            CREATE INDEX IF NOT EXISTS idx_workflow_status 
            ON application_workflow_status(application_id, step_status);
        '''))
        
        conn.execute(text('''
            CREATE INDEX IF NOT EXISTS idx_workflow_app_step 
            ON application_workflow_status(application_id, workflow_step_id);
        '''))
        
        conn.commit()
    
    print("✅ ApplicationWorkflowStatus table created successfully")

def downgrade():
    """Remove application_workflow_status table"""
    from sqlalchemy import text
    
    with db.engine.connect() as conn:
        conn.execute(text('DROP TABLE IF EXISTS application_workflow_status CASCADE;'))
        conn.commit()
        
    print("❌ ApplicationWorkflowStatus table removed")

if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        upgrade()