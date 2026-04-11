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
from sqlalchemy import func


@click.command()
@with_appcontext
def init_db():
    """Initialize the database with initial data."""
    import os
    click.echo('Initializing database with initial data...')
    
    try:
        # Create admin user if not exists
        admin_email = 'mswdmabitac@gmail.com'
        admin_user = User.query.filter(func.lower(User.email) == admin_email).first()
        if not admin_user:
            # SECURITY: For production, use strong password from environment variable
            admin_password = os.environ.get('ADMIN_PASSWORD', 'MabitacMSWD_2025')
            if admin_password == 'MabitacMSWD_2025' and os.environ.get('FLASK_ENV') == 'production':
                click.echo('⚠️  WARNING: Using default admin password in production!')
                click.echo('Set ADMIN_PASSWORD environment variable for security.')
            
            admin_user = User(
                email=admin_email,
                password_hash=generate_password_hash(admin_password, method='pbkdf2:sha256'),
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

        # Create sample community user if not exists (dev/testing only)
        sample_email = 'user1@test.com'
        sample_user = User.query.filter(func.lower(User.email) == sample_email).first()
        if not sample_user:
            # SECURITY: Sample user password - should only exist in dev environments
            sample_password = os.environ.get('SAMPLE_USER_PASSWORD', 'password123')
            sample_user = User(
                email=sample_email,
                password_hash=generate_password_hash(sample_password, method='pbkdf2:sha256'),
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
                    start_date='2026-01-01',
                    end_date='2026-12-31',
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

        # Link requirements to programs
        # Define which requirements are needed for each program type
        program_requirements_mapping = {
            'AICS': {
                'documents': [
                    'Valid ID',
                    'PSA Birth Certificate',
                    'Barangay Indigency Certificate',
                    'Proof of Income'
                ],
                'qualifications': [
                    'Low Income Family',
                    'Resident of Mabitac'
                ]
            },
            'ESA': {
                'documents': [
                    'Valid ID',
                    'Barangay Report',
                    'Barangay Indigency Certificate'
                ],
                'qualifications': [
                    'Fire Victim',
                    'Typhoon Victim',
                    'Resident of Mabitac'
                ]
            },
            'CA': {
                'documents': [
                    'Valid ID',
                    'Proof of Income',
                    'Proof of Business',
                    'Barangay Indigency Certificate'
                ],
                'qualifications': [
                    'Low Income Family',
                    'Resident of Mabitac'
                ]
            }
        }

        program_requirements_created = 0
        
        # Get all programs
        all_programs = Programs.query.all()
        
        for program in all_programs:
            # Get requirements mapping for this program type
            requirements_config = program_requirements_mapping.get(program.program_type, {})
            
            for req_type in ['documents', 'qualifications']:
                req_names = requirements_config.get(req_type, [])
                
                for req_name in req_names:
                    # Find the requirement
                    requirement = Requirements.query.filter_by(
                        requirement_name=req_name,
                        requirement_type='document' if req_type == 'documents' else 'qualification'
                    ).first()
                    
                    if requirement:
                        # Check if this program-requirement link already exists
                        existing_link = ProgramRequirements.query.filter_by(
                            program_id=program.id,
                            requirement_id=requirement.id
                        ).first()
                        
                        if not existing_link:
                            # Create the link
                            program_req = ProgramRequirements(
                                program_id=program.id,
                                requirement_id=requirement.id,
                                is_mandatory=True,
                                is_completed=False,
                                document_status='pending'
                            )
                            db.session.add(program_req)
                            program_requirements_created += 1

        if program_requirements_created > 0:
            click.echo(f'✅ Created {program_requirements_created} program-requirement links')
        else:
            click.echo('✅ Program requirements already linked')

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
            ShelterPhotos, Notifications, Applications, CommunityUsers, User, Assessment, AssessmentDocument,
            ApplicationWorkflowStatus, UserActivityLog
        )
        
        # Clear in proper order to respect foreign key constraints
        CALDocuments.query.delete()
        ApplicationDocumentUploads.query.delete()
        ApplicationDocuments.query.delete()
        ShelterPhotos.query.delete()
        
        # Delete notifications for community users only
        community_user_ids = db.session.query(User.id).filter_by(role='community').subquery()
        Notifications.query.filter(Notifications.user_id.in_(community_user_ids)).delete(synchronize_session='fetch')
        
        # Delete assessment documents first (foreign key dependency on assessments)
        AssessmentDocument.query.filter(AssessmentDocument.assessment_id.in_(
            db.session.query(Assessment.id).join(Applications).filter(Applications.user_id.in_(community_user_ids))
        )).delete(synchronize_session='fetch')
        
        # Delete assessments by community users (foreign key dependency on applications)
        Assessment.query.filter(Assessment.application_id.in_(
            db.session.query(Applications.id).filter(Applications.user_id.in_(community_user_ids))
        )).delete(synchronize_session='fetch')
        
        # Delete workflow status records for community users' applications
        ApplicationWorkflowStatus.query.filter(ApplicationWorkflowStatus.application_id.in_(
            db.session.query(Applications.id).filter(Applications.user_id.in_(community_user_ids))
        )).delete(synchronize_session='fetch')
        
        # Delete activity logs for community users
        UserActivityLog.query.filter(UserActivityLog.user_id.in_(community_user_ids)).delete(synchronize_session='fetch')
        
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
    """Populate database with dummy data (DEPRECATED - use 'flask db upgrade' instead)."""
    click.echo('⚠️  This command is deprecated!')
    click.echo('')
    click.echo('Dummy data is now handled by Alembic migrations.')
    click.echo('To populate test data, use:')
    click.echo('')
    click.echo('  flask db upgrade')
    click.echo('')
    click.echo('This will automatically run all pending migrations including the data migration.')
    click.echo('The data migration file is: migrations/versions/add_dummy_data_v1.py')
    click.echo('')
    click.echo('✅ Migration-based approach benefits:')
    click.echo('   • Data seeding is version-controlled')
    click.echo('   • Can be automated in CI/CD pipelines')
    click.echo('   • Matches production deployment patterns')
    click.echo('   • Easily reversible with downgrade')


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


def _set_default_super_admin_credentials():
    """Create or reset the default super admin account to fixed credentials."""
    email = 'super_admin26@email.com'
    password = 'AYUDASuper_2026*'

    user = User.query.filter(func.lower(User.email) == email.lower()).first()

    if user:
        user.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        user.role = 'super_admin'

        # Ensure basic profile fields are populated for templates/audit views.
        if not user.first_name:
            user.first_name = 'Super'
        if not user.last_name:
            user.last_name = 'Admin'

        click.echo('✅ Super admin account found and reset.')
    else:
        user = User(
            email=email,
            password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
            first_name='Super',
            middle_name='',
            last_name='Admin',
            role='super_admin',
        )
        db.session.add(user)
        click.echo('✅ Super admin account created.')

    db.session.commit()
    click.echo(f'Email: {email}')
    click.echo(f'Password: {password}')


@click.command('add-super-admin')
@with_appcontext
def add_super_admin():
    """Create the default super admin account, or reset it if it already exists."""
    try:
        _set_default_super_admin_credentials()
    except Exception as e:
        db.session.rollback()
        click.echo(f'❌ Error adding super admin account: {e}')


@click.command('reset-super-admin')
@with_appcontext
def reset_super_admin():
    """Reset the default super admin account credentials (creates it if missing)."""
    try:
        _set_default_super_admin_credentials()
    except Exception as e:
        db.session.rollback()
        click.echo(f'❌ Error resetting super admin account: {e}')


def init_app(app):
    """Register CLI commands with Flask app."""
    app.cli.add_command(init_db)
    app.cli.add_command(clear_dummy_data)
    app.cli.add_command(populate_dummy_data)
    app.cli.add_command(reset_migrations)
    app.cli.add_command(fix_migration)
    app.cli.add_command(add_super_admin)
    app.cli.add_command(reset_super_admin)