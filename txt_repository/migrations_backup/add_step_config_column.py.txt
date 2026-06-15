#!/usr/bin/env python3
"""
Migration: Add step_config column to program_workflow_steps table
Date: January 28, 2026
Description: Adds step_config TEXT column to store JSON configuration for step-specific settings
"""

import psycopg2
import os
import sys

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def run_migration():
    """Add step_config column to program_workflow_steps table"""
    conn = None
    cur = None
    try:
        # Connect to PostgreSQL using config
        conn = psycopg2.connect(Config.SQLALCHEMY_DATABASE_URI)
        cur = conn.cursor()
        
        print("Starting migration: Add step_config column...")
        
        # Check if column already exists
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'program_workflow_steps' 
            AND column_name = 'step_config'
        """)
        
        if cur.fetchone():
            print("Column 'step_config' already exists. Skipping addition.")
        else:
            # Add step_config column
            cur.execute("""
                ALTER TABLE program_workflow_steps 
                ADD COLUMN step_config TEXT
            """)
            print("Added 'step_config' column to 'program_workflow_steps' table.")
        
        # Commit the changes
        conn.commit()
        print("Migration completed successfully!")
        
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()