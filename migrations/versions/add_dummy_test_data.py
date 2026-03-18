"""Add dummy test data for analytics

Revision ID: dummy_data_001
Revises: 936217dd0e15
Create Date: 2026-03-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dummy_data_001'
down_revision = '936217dd0e15'
branch_labels = None
depends_on = None


def upgrade():
    """Add 50 test users with 2 years of application history (2024-2026)
    
    Target: 18-25 applications per month (~540 total for 24 months)
    Distribution: 10-11 applications per user (50 users)
    """
    
    bind = op.get_bind()
    
    # Get the admin user ID for reference
    admin_result = bind.execute(sa.text("SELECT id FROM users WHERE email = 'MSWDMabitac@gmail.com' LIMIT 1"))
    admin_user = admin_result.fetchone()
    admin_id = admin_user[0] if admin_user else 1
    
    # Get program IDs
    programs_result = bind.execute(sa.text("SELECT id FROM programs ORDER BY id LIMIT 10"))
    programs = programs_result.fetchall()
    program_ids = [p[0] for p in programs]
    
    if not program_ids:
        return
    
    # Pre-generated password hash for 'password123' using pbkdf2:sha256
    password_hash = 'pbkdf2:sha256:600000$L8xN9kM7$9f8c5d8c1f8c5d8c1f8c5d8c1f8c5d8c1f8c5d8c'
    
    first_names = ['Maria', 'Juan', 'Pedro', 'Rosa', 'Carlos', 'Ana', 'Jose', 'Antonio', 'Isabel', 'Miguel']
    last_names = ['Santos', 'Dela Cruz', 'Reyes', 'Gonzales', 'Lopez', 'Garcia', 'Martinez', 'Fernandez', 'Rivera', 'Cruz']
    
    barangays = ['Kinabuchi', 'Layuhan', 'Mabitac', 'Bagong-bayan', 'Cawayan']
    
    # Create test users in batches
    user_ids = []
    
    for i in range(1, 51):
        first_name = first_names[i % len(first_names)]
        last_name = last_names[i % len(last_names)]
        email = f'testuser{i}@test.com'
        
        # Insert user
        result = bind.execute(sa.text("""
            INSERT INTO users (email, password_hash, first_name, last_name, role, created_at)
            VALUES (:email, :password_hash, :first_name, :last_name, 'community', '2024-01-01')
            RETURNING id
        """), {
            'email': email,
            'password_hash': password_hash,
            'first_name': first_name,
            'last_name': last_name
        })
        user_id = result.scalar()
        user_ids.append(user_id)
        
        # Create community profile
        bind.execute(sa.text("""
            INSERT INTO community_users 
            (user_id, age, gender, barangay, address, is_currently_employed, is_student, is_solo_parent, is_pwd, family_annual_income, created_at)
            VALUES (:user_id, :age, :gender, :barangay, :address, :is_employed, :is_student, :is_solo_parent, :is_pwd, :income, '2024-01-01')
        """), {
            'user_id': user_id,
            'age': 25 + (i % 40),
            'gender': 'M' if i % 2 == 0 else 'F',
            'barangay': barangays[i % len(barangays)],
            'address': f'Sample Address {i}',
            'is_employed': i % 3 == 0,
            'is_student': i % 5 == 0,
            'is_solo_parent': i % 7 == 0,
            'is_pwd': i % 10 == 0,
            'income': 50000 + (i * 1000)
        })
    
    # Create applications spanning 2024-2026
    # Target: 18-25 per month = ~540 total for 24 months = 10.8 per user
    # Distribution: 10-11 applications per user
    
    app_count = 0
    for user_idx, user_id in enumerate(user_ids):
        # Each user gets 10-11 applications over the 2-year period
        # This should give us ~20-22 applications per month on average
        num_applications = 10 + (user_idx % 2)  # 10 or 11 per user
        
        for app_idx in range(num_applications):
            # Distribute applications across ~1172 days (Jan 2024 - Mar 2026)
            # Each app gets ~113 days apart for even distribution
            days_offset = (app_idx * 113) + (user_idx * 2)
            
            # Vary status distribution
            rand_val = (user_idx + app_idx) % 10
            if rand_val < 5:
                status = 'pending'
                doc_status = 'pending'
                reviewed_by_val = None
            elif rand_val < 8:
                status = 'approved'
                doc_status = 'approved'
                reviewed_by_val = admin_id
            elif rand_val < 9:
                status = 'rejected'
                doc_status = 'rejected'
                reviewed_by_val = admin_id
            else:
                status = 'claimed'
                doc_status = 'approved'
                reviewed_by_val = admin_id
            
            program_id = program_ids[app_count % len(program_ids)]
            verification_code = f'TEST{user_id:04d}{app_count:04d}'
            
            bind.execute(sa.text("""
                INSERT INTO applications 
                (user_id, program_id, application_status, document_upload_status, 
                 application_date, review_date, reviewed_by, submission_deadline, 
                 verification_code, code_generated_at, created_at, updated_at)
                VALUES (:user_id, :program_id, :status, :doc_status,
                        '2024-01-01'::date + :days_offset * interval '1 day',
                        CASE WHEN :reviewed_by IS NOT NULL 
                             THEN '2024-01-01'::date + (:days_offset + 5) * interval '1 day' 
                             ELSE NULL 
                        END,
                        :reviewed_by,
                        '2024-01-01'::date + (:days_offset + 30) * interval '1 day',
                        :verification_code,
                        '2024-01-01'::date + :days_offset * interval '1 day',
                        '2024-01-01'::date + :days_offset * interval '1 day',
                        NOW())
            """), {
                'user_id': user_id,
                'program_id': program_id,
                'status': status,
                'doc_status': doc_status,
                'days_offset': days_offset,
                'reviewed_by': reviewed_by_val,
                'verification_code': verification_code
            })
            
            app_count += 1


def downgrade():
    """Remove dummy test data"""
    bind = op.get_bind()
    
    # Delete applications by test users (foreign key dependency)
    bind.execute(sa.text("""
        DELETE FROM applications 
        WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'testuser%@test.com')
    """))
    
    # Delete community profiles for test users
    bind.execute(sa.text("""
        DELETE FROM community_users 
        WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'testuser%@test.com')
    """))
    
    # Delete test users
    bind.execute(sa.text("""
        DELETE FROM users 
        WHERE email LIKE 'testuser%@test.com'
    """))
