"""
Flask CLI commands for database operations
"""
import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models import (User, Programs, Applications, CommunityUsers, AdminUsers, 
                       Requirements, ProgramRequirements, ShelterPhotos, 
                       ProgramWorkflowSteps, ApplicationDocuments, 
                       ApplicationDocumentUploads, CALDocuments,
                       Announcements, Notifications)
from werkzeug.security import generate_password_hash


@click.command()
@with_appcontext
def init_db():
    """Initialize the data  base with initial data."""
    click.echo('Initializing database with initial data...')
    
    try:
        # Create admin user if not exists
        admin_user = User.query.filter_by(email='MSWDMabitac@gmail.com').first()
        if not admin_user:
            admin_user = User(
                email='MSWDMabitac@gmail.com',
                password_hash=generate_password_hash('MabitacMSWD_2025'),
                first_name='MSWD',
                middle_name='',
                last_name='Mabitac',
                role='admin'
            )
            db.session.add(admin_user)
            db.session.flush()
            
            # Create admin profile
            admin_profile = AdminUsers(user_id=admin_user.id)
            db.session.add(admin_profile)
            click.echo('✅ Admin user created')
        else:
            click.echo('✅ Admin user already exists')

        # Create sample community user if not exists
        sample_user = User.query.filter_by(email='user1@test.com').first()
        if not sample_user:
            sample_user = User(
                email='user1@test.com',
                password_hash=generate_password_hash('password123'),
                first_name='Juan',
                middle_name='A',
                last_name='Dela Cruz',
                role='community'
            )
            db.session.add(sample_user)
            click.echo('✅ Sample user created')
        else:
            click.echo('✅ Sample user already exists')

        # Create programs if not exist
        programs_data = [
            {
                'name': 'Financial Assistance Program',
                'type': 'AICS',
                'period': 'Ongoing',
                'priority_group': 'Low-income families',
                'beneficiary_limit': 100,
                'income_range': '₱0 - ₱150,000',
                'description': 'Provides financial support to families in need for emergencies and basic necessities'
            },
            {
                'name': 'Burial Assistance Program',
                'type': 'AICS',
                'period': 'Emergency',
                'priority_group': 'Families in need',
                'beneficiary_limit': 50,
                'income_range': '₱0 - ₱200,000',
                'description': 'Provides financial support to families in need for burial and funeral services'
            },
            {
                'name': 'Educational Assistance Program',
                'type': 'AICS',
                'period': 'Semi-Annual',
                'priority_group': 'Students from low-income families',
                'beneficiary_limit': 200,
                'income_range': '₱0 - ₱150,000',
                'description': 'Educational financial assistance program for elementary to college students'
            },
            {
                'name': 'Medical Assistance Program',
                'type': 'AICS',
                'period': 'Ongoing',
                'priority_group': 'Low-income families needing medical help',
                'beneficiary_limit': 150,
                'income_range': '₱0 - ₱200,000',
                'description': 'Healthcare support including medicine subsidies, hospital bills, and medical procedures'
            },
            {
                'name': 'Fire Disaster',
                'type': 'ESA',
                'period': 'Emergency',
                'priority_group': 'Fire victims',
                'beneficiary_limit': 30,
                'income_range': 'All income levels',
                'description': 'Temporary shelter and housing assistance for families affected by fire incidents'
            },
            {
                'name': 'Typhoon Disaster',
                'type': 'ESA',
                'period': 'Emergency',
                'priority_group': 'Typhoon victims',
                'beneficiary_limit': 50,
                'income_range': 'All income levels',
                'description': 'Temporary shelter and housing assistance for families affected by typhoon incidents'
            },
            {
                'name': 'Capital Assistance Program',
                'type': 'CA',
                'period': 'Monthly',
                'priority_group': 'Aspiring entrepreneurs',
                'beneficiary_limit': 75,
                'income_range': '₱0 - ₱300,000',
                'description': 'Support for microenterprise development and livelihood projects'
            }
        ]

        programs_created = 0
        for prog_data in programs_data:
            existing_program = Programs.query.filter_by(program_name=prog_data['name']).first()
            if not existing_program:
                program = Programs(
                    program_name=prog_data['name'],
                    program_type=prog_data['type'],
                    program_period=prog_data['period'],
                    priority_group=prog_data['priority_group'],
                    beneficiary_limit=prog_data['beneficiary_limit'],
                    income_range=prog_data['income_range'],
                    start_date='2024-01-01',
                    end_date='2024-12-31',
                    description=prog_data['description'],
                    user_id=admin_user.id,
                    is_active=True,
                    allow_online_upload=True
                )
                db.session.add(program)
                programs_created += 1

        if programs_created > 0:
            click.echo(f'✅ Created {programs_created} programs')
        else:
            click.echo('✅ Programs already exist')

        # Create requirements 
        document_requirements_data = [
            ('Valid ID', 'Any government-issued ID (PhilID, Driver\'s License, Passport, etc.)'),
            ('PSA Birth Certificate', 'Photocopy of birth certificate from PSA (Philippine Statistics Authority)'),
            ('Certificate of Enrollment / Registration (COR)', 'Current certificate of enrollment/registration from school for current semester/quarter'),
            ('Certificate of Grades (COG)', 'Latest grades from previous semester/quarter'),
            ('Student ID', 'Valid student identification card issued by the current school (School ID)'),
            ('Barangay Report', 'Barangay report for disaster-affected applicants'),
            ('Barangay Indigency Certificate', 'Certificate of Indigency from Barangay'),
            ('Barangay Clearance', 'Barangay clearance certificate'),
            ('Medical Certificate', 'Medical certificate from licensed physician'),
            ('Death Certificate', 'PSA Death Certificate of deceased'),
            ('Proof of Income', 'Latest payslip, ITR, or certificate of income'),
            ('Funeral Contract', 'Contract or agreement with funeral service provider'),
            ('Hospital Bills/Medical Records', 'Medical bills, prescriptions, or hospital records'),
            ('PWD ID', 'Valid Person with Disability identification card'),
            ('Senior Citizen ID', 'Valid senior citizen identification card'),
            ('Solo Parent ID', 'Valid solo parent identification card'),
            ('Proof of Business', 'Business permit, DTI registration, or business-related documents')
        ]

        qualification_requirements_data = [
            ('Student', 'Currently enrolled in any educational institution'),
            ('Solo Parent', 'Registered solo parent with valid ID'),
            ('Low Income Family', 'Family annual income below poverty threshold'),
            ('Indigent Family', 'Family identified as indigent by barangay'),
            ('Person with Disability (PWD)', 'Registered PWD with valid ID'),
            ('Senior Citizen', '60 years old and above with valid ID'),
            ('Resident of Mabitac', 'Bonafide resident of Mabitac, Laguna'),
            ('Fire Victim', 'Affected by fire incident (with barangay report)'),
            ('Typhoon Victim', 'Affected by typhoon/calamity (with barangay report)')
        ]

        requirements_created = 0
        
        # Create document requirements
        for name, description in document_requirements_data:
            existing_req = Requirements.query.filter_by(requirement_name=name, requirement_type='document').first()
            if not existing_req:
                requirement = Requirements(
                    requirement_name=name,
                    requirement_type='document',
                    description=description
                )
                db.session.add(requirement)
                requirements_created += 1

        # Create qualification requirements
        for name, description in qualification_requirements_data:
            existing_req = Requirements.query.filter_by(requirement_name=name, requirement_type='qualification').first()
            if not existing_req:
                requirement = Requirements(
                    requirement_name=name,
                    requirement_type='qualification',
                    description=description
                )
                db.session.add(requirement)
                requirements_created += 1

        if requirements_created > 0:
            click.echo(f'✅ Created {requirements_created} requirements')
        else:
            click.echo('✅ Requirements already exist')

        # Commit all changes
        db.session.commit()
        click.echo('🎉 Database initialization completed successfully!')
        
    except Exception as e:
        click.echo(f'❌ Error initializing database: {e}')
        db.session.rollback()


@click.command()
@with_appcontext
def clear_dummy_data():
    """Clear all dummy/test data while preserving admin and core setup."""
    click.echo('Clearing dummy data...')
    
    if not click.confirm('This will delete all community users and applications. Continue?'):
        click.echo('Operation cancelled.')
        return
    
    try:
        from app.models import (
            CALDocuments, ApplicationDocumentUploads, ApplicationDocuments, 
            ShelterPhotos, Notifications, Applications, CommunityUsers, User
        )
        
        # Clear in proper order to respect foreign key constraints
        CALDocuments.query.delete()
        ApplicationDocumentUploads.query.delete()
        ApplicationDocuments.query.delete()
        ShelterPhotos.query.delete()
        
        # Delete notifications for community users only
        community_user_ids = db.session.query(User.id).filter_by(role='community').subquery()
        Notifications.query.filter(Notifications.user_id.in_(community_user_ids)).delete(synchronize_session='fetch')
        
        # Delete applications by community users
        Applications.query.filter(Applications.user_id.in_(community_user_ids)).delete(synchronize_session='fetch')
        
        # Delete community profiles and users
        CommunityUsers.query.delete()
        User.query.filter_by(role='community').delete()
        
        db.session.commit()
        click.echo('✅ Dummy data cleared successfully!')
        
    except Exception as e:
        click.echo(f'❌ Error clearing dummy data: {e}')
        db.session.rollback()


@click.command()
@with_appcontext
def populate_dummy_data():
    """Populate database with dummy data for testing."""
    click.echo('Populating dummy data...')
    
    try:
        # Import and run the populate_dummy_data function
        from populate_dummy_data import populate_dummy_data as populate_func
        success = populate_func()
        
        if success:
            click.echo('🎉 Dummy data population completed successfully!')
        else:
            click.echo('❌ Dummy data population failed!')
            
    except Exception as e:
        click.echo(f'❌ Error populating dummy data: {e}')


@click.command()
@with_appcontext
def reset_migrations():
    """Reset migrations to a clean state (DEVELOPMENT ONLY)."""
    if not click.confirm('⚠️  This will reset all migrations and recreate the database. Continue?'):
        click.echo('Operation cancelled.')
        return
        
    try:
        import os
        from sqlalchemy import text
        
        click.echo('🔄 Resetting migration state...')
        
        # Drop all tables to clean slate
        click.echo('   Dropping all tables...')
        db.drop_all()
        
        # Remove the problematic migration file
        migration_file = 'migrations/versions/1820bb72ab9d_initial_migration_with_all_models.py'
        if os.path.exists(migration_file):
            os.remove(migration_file)
            click.echo(f'   Removed {migration_file}')
        
        # Clear alembic version table if it exists
        try:
            db.session.execute(text('DROP TABLE IF EXISTS alembic_version CASCADE'))
            db.session.commit()
        except Exception:
            pass
        
        click.echo('✅ Migration state reset successfully!')
        click.echo('')
        click.echo('📝 Next steps:')
        click.echo('1. flask db migrate -m "Initial migration"')
        click.echo('2. flask db upgrade')
        click.echo('3. flask init-db')
        
    except Exception as e:
        click.echo(f'❌ Error resetting migrations: {e}')
        db.session.rollback()


@click.command()
@with_appcontext
def fix_migration():
    """Fix the current migration downgrade issues."""
    try:
        from sqlalchemy import text
        
        click.echo('🔧 Fixing migration downgrade issues...')
        
        # Mark the current migration as not applied
        try:
            db.session.execute(text("DELETE FROM alembic_version"))
            db.session.commit()
            click.echo('✅ Cleared alembic version table')
        except Exception as e:
            click.echo(f'⚠️  Could not clear alembic version: {e}')
            
        # Now we can safely upgrade again
        click.echo('')
        click.echo('📝 Run these commands to complete the fix:')
        click.echo('1. flask db upgrade')
        click.echo('2. flask init-db (if needed)')
        
    except Exception as e:
        click.echo(f'❌ Error fixing migration: {e}')
        db.session.rollback()


def init_app(app):
    """Register CLI commands with Flask app."""
    app.cli.add_command(init_db)
    app.cli.add_command(clear_dummy_data)
    app.cli.add_command(populate_dummy_data)
    app.cli.add_command(reset_migrations)
    app.cli.add_command(fix_migration)