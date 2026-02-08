# Database Migration Guide with Alembic/Flask-Migrate

This guide explains how to use Alembic (via Flask-Migrate) for database schema versioning, migrations, and rollback capabilities in your Flask application.

## 🚀 Initial Setup

### 1. Initialize Migration Repository
```bash
flask db init
```
This creates a `migrations/` directory with Alembic configuration.

### 2. Create Initial Migration
```bash
flask db migrate -m "Initial migration with all models"
```
This generates the first migration script based on your current SQLAlchemy models.

### 3. Apply Migration to Database
```bash
flask db upgrade
```
This creates all the tables in your database based on the migration.

### 4. Initialize with Base Data
```bash
flask init-db
```
This adds the initial admin user, programs, and requirements to the database.

### 5. Add Dummy Data (Optional)
```bash
flask populate-dummy-data
```
This adds test users and applications for development/testing.

## 📋 Common Migration Commands

### Creating New Migrations
When you modify your models, create a new migration:
```bash
# Auto-generate migration from model changes
flask db migrate -m "Add new column to users table"

# Apply the migration
flask db upgrade
```

### Rolling Back Migrations
```bash
# Downgrade to previous migration
flask db downgrade

# Downgrade to specific revision
flask db downgrade <revision_id>

# Show current migration status
flask db current

# Show migration history
flask db history
```

### Manual Migration Management
```bash
# Show pending migrations
flask db show

# Upgrade to specific revision
flask db upgrade <revision_id>

# Generate empty migration file for custom changes
flask db revision -m "Custom data migration"
```

## 🔧 Migration File Types

### 1. Schema Migrations (Auto-generated)
These handle table structure changes:
- Adding/removing columns
- Creating/dropping tables
- Adding/removing indexes
- Modifying column types

Example migration file structure:
```python
def upgrade():
    # Schema changes to apply
    op.add_column('users', sa.Column('new_field', sa.String(100)))
    
def downgrade():
    # Schema changes to rollback
    op.drop_column('users', 'new_field')
```

### 2. Data Migrations (Manual)
These handle data changes:
- Inserting initial data
- Updating existing records
- Data transformations

Example data migration:
```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

def upgrade():
    # Create a temporary table representation
    programs_table = table('programs',
        column('id', sa.Integer),
        column('program_name', sa.String),
        column('program_type', sa.String)
    )
    
    # Insert data
    op.bulk_insert(programs_table, [
        {'program_name': 'New Program', 'program_type': 'AICS'}
    ])

def downgrade():
    # Remove the data
    op.execute("DELETE FROM programs WHERE program_name = 'New Program'")
```

## 🗂️ Project Migration Structure

```
migrations/
├── alembic.ini           # Alembic configuration
├── env.py               # Migration environment setup
├── script.py.mako       # Template for new migrations
└── versions/            # Migration files
    ├── 001_initial_migration.py
    ├── 002_add_user_fields.py
    └── 003_create_programs.py
```

## 🎯 Best Practices

### 1. Migration Naming
Use descriptive names:
```bash
flask db migrate -m "Add profile_picture_url to users"
flask db migrate -m "Create notifications table"
flask db migrate -m "Add indexes for performance"
```

### 2. Review Before Applying
Always review generated migrations before applying:
```bash
# Generate migration
flask db migrate -m "Changes description"

# Review the generated file in migrations/versions/

# Apply if looks correct
flask db upgrade
```

### 3. Database Backup
Always backup production database before migrations:
```bash
# PostgreSQL backup
pg_dump -U username -h localhost database_name > backup_$(date +%Y%m%d_%H%M%S).sql

# Apply migration
flask db upgrade

# If issues occur, restore backup
psql -U username -h localhost database_name < backup_file.sql
```

### 4. Environment-Specific Migrations
Use different configurations for different environments:

```python
# config.py
class DevelopmentConfig(Config):
    SQLALCHEMY_DATABASE_URI = 'postgresql://user:pass@localhost/dev_db'

class ProductionConfig(Config):
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
```

## 🚨 Troubleshooting

### 1. Migration Conflicts
If multiple developers create migrations simultaneously:
```bash
# Merge migration heads
flask db merge -m "Merge migration heads" <head1> <head2>
```

### 2. Failed Migration
If a migration fails midway:
```bash
# Check current state
flask db current

# Manual fix in database, then mark as complete
flask db stamp <revision_id>
```

### 3. Reset Migration History (Development Only)
To start fresh in development:
```bash
# Drop all tables
flask db downgrade base

# Delete migration files (keep migrations/ directory)
rm migrations/versions/*.py

# Create new initial migration
flask db migrate -m "Fresh start"
flask db upgrade
```

## 📊 Production Deployment Workflow

### 1. Development
```bash
# Make model changes
# Generate migration
flask db migrate -m "Feature description"

# Test locally
flask db upgrade
```

### 2. Staging
```bash
# Deploy code
git pull origin main

# Apply migrations
flask db upgrade

# Test functionality
```

### 3. Production
```bash
# Backup database
pg_dump production_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Deploy code (with maintenance mode on)
git pull origin main

# Apply migrations
flask db upgrade

# Verify and turn off maintenance mode
```

## 🔄 Rollback Strategy

### 1. Immediate Rollback
```bash
# Rollback to previous version
flask db downgrade

# If multiple migrations need rollback
flask db downgrade <safe_revision_id>
```

### 2. Data Recovery
For data migrations that can't be auto-reversed:
```bash
# Restore from backup
psql -U username database_name < backup_file.sql

# Re-apply safe migrations if needed
flask db upgrade <safe_revision_id>
```

## 🏃‍♂️ Quick Start Commands

```bash
# First time setup
flask db init
flask db migrate -m "Initial migration"  
flask db upgrade
flask init-db

# Regular workflow
flask db migrate -m "Your changes description"
flask db upgrade

# Check status
flask db current
flask db history
```

This migration system provides you with:
- ✅ **Schema Versioning**: Track all database changes
- ✅ **Automatic Script Generation**: Generate migrations from model changes  
- ✅ **Rollback Capabilities**: Safely undo changes
- ✅ **Team Collaboration**: Share migrations via version control
- ✅ **Environment Management**: Different configs per environment
- ✅ **Data Migrations**: Handle data transformations safely