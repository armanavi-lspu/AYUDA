"""Add dummy data for testing

Revision ID: add_dummy_data_v1
Revises: c859c3ce65bc
Create Date: 2026-03-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timedelta
import random
import numpy as np
from werkzeug.security import generate_password_hash


# revision identifiers, used by Alembic.
revision = 'add_dummy_data_v1'
down_revision = 'c859c3ce65bc'
branch_labels = None
depends_on = None


def upgrade():
    """Populate test data"""
    
    # Get the connection
    connection = op.get_bind()
    
    # Check if TEST data already exists (idempotency) - only check for test user pattern
    result = connection.execute(sa.text("SELECT COUNT(*) FROM users WHERE role = 'community' AND email LIKE 'user%@test.com'"))
    test_user_count = result.scalar()
    
    if test_user_count > 0:
        print("ℹ️  Test users already exist. Skipping population.")
        return
    
    print("🔄 Populating dummy data...")
    
    # Get the admin user
    admin_result = connection.execute(sa.text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))
    admin_row = admin_result.fetchone()
    if not admin_row:
        print("❌ No admin user found. Skipping dummy data population.")
        return
    
    admin_id = admin_row[0]
    
    # Get available programs
    programs_result = connection.execute(sa.text("SELECT id FROM programs LIMIT 20"))
    program_ids = [row[0] for row in programs_result.fetchall()]
    
    if not program_ids:
        print("❌ No programs found. Skipping dummy data population.")
        return
    
    # Data for test users
    barangays = ['Amuyong', 'Bayanihan', 'Lambac', 'Libis ng Nayon', 'Lucong', 
                 'Maligaya', 'Masikap', 'Matalatala', 'Nanguma', 'Numero Uno', 
                 'Paagahan', 'Pag-Asa', 'San Antonio', 'San Miguel', 'Sinagtala']
    
    sitios = ['Sitio 1', 'Sitio 2', 'Sitio 3', 'Sitio 4', 'Purok 1', 'Purok 2']
    
    first_names = ['Juan', 'Maria', 'Pedro', 'Mae Belle', 'Jose', 'Marc Josue', 'Jemcent', 'Elena', 
                   'Ramon', 'Sofia', 'Mathel', 'Carmen', 'Luis', 'Teresa', 'Antonio',
                   'Gabriel', 'Arman', 'Fernando', 'Avi', 'Ricardo']
    
    last_names = ['Dela Cruz', 'Dimaano', 'Reyes', 'Garcia', 'Abulencia', 'Mendoza', 
                  'Torres', 'Bitabara', 'Sansano', 'Rivera', 'Bautista', 'Fernandez',
                  'Castillo', 'Morales', 'Diaz', 'Pren']
    
    occupations = ['Farmer', 'Driver', 'Store Owner', 'Teacher', 'Security Guard', 
                   'Factory Worker', 'Carpenter', 'Electrician']
    
    disability_types = ['Visual Impairment', 'Hearing Impairment', 'Physical Disability', 
                       'Mental/Psychosocial', 'Speech Impairment']
    
    # Create 20 community users
    print("👥 Creating 20 community users...")
    created_users = []
    
    for i in range(20):
        first_name = random.choice(first_names)
        last_name = random.choice(last_names)
        email = f'user{i+21}@test.com'
        
        # Check if user already exists
        check_result = connection.execute(sa.text("SELECT id FROM users WHERE email = :email"), {'email': email})
        if check_result.fetchone():
            continue
        
        # Generate birth date
        birth_year = random.randint(1960, 2005)
        birth_month = random.randint(1, 12)
        birth_day = random.randint(1, 28)
        
        # Calculate age
        today = datetime.now()
        age = today.year - birth_year
        if today.month < birth_month or (today.month == birth_month and today.day < birth_day):
            age -= 1
        
        # Insert user
        insert_user_query = sa.text("""
            INSERT INTO users (email, password_hash, first_name, middle_name, last_name, role, created_at)
            VALUES (:email, :password_hash, :first_name, :middle_name, :last_name, :role, :created_at)
        """)
        
        connection.execute(insert_user_query, {
            'email': email,
            'password_hash': generate_password_hash('password123', method='pbkdf2:sha256'),
            'first_name': first_name,
            'middle_name': random.choice(['A', 'B', 'C', 'D', 'E', 'M', 'L', '']),
            'last_name': last_name,
            'role': 'community',
            'created_at': datetime.utcnow()
        })
        
        # Get the created user ID
        new_user_result = connection.execute(sa.text("SELECT id FROM users WHERE email = :email"), {'email': email})
        user_id = new_user_result.scalar()
        created_users.append(user_id)
        
        # Create community profile
        is_employed = random.choice([True, False])
        is_pwd = random.choice([True, False]) if random.random() < 0.1 else False
        
        # Generate income
        income_bracket = random.random()
        if income_bracket < 0.70:
            family_income = random.randint(30000, 150000)
        elif income_bracket < 0.95:
            family_income = random.randint(150001, 400000)
        else:
            family_income = random.randint(400001, 800000)
        
        insert_community_query = sa.text("""
            INSERT INTO community_users (
                user_id, age, mobile_no, birth_month, birth_day, birth_year, gender,
                barangay, sitio, address, municipality, is_currently_employed, occupation,
                is_student, is_solo_parent, is_pwd, disability_type, family_annual_income
            ) VALUES (
                :user_id, :age, :mobile_no, :birth_month, :birth_day, :birth_year, :gender,
                :barangay, :sitio, :address, :municipality, :is_employed, :occupation,
                :is_student, :is_solo_parent, :is_pwd, :disability_type, :family_income
            )
        """)
        
        connection.execute(insert_community_query, {
            'user_id': user_id,
            'age': age,
            'mobile_no': f'09{random.randint(100000000, 999999999)}',
            'birth_month': birth_month,
            'birth_day': birth_day,
            'birth_year': birth_year,
            'gender': random.choice(['Male', 'Female', 'Other']),
            'barangay': random.choice(barangays),
            'sitio': random.choice(sitios),
            'address': f'{random.randint(1, 999)} Main St, {random.choice(sitios)}',
            'municipality': 'Mabitac',
            'is_employed': is_employed,
            'occupation': random.choice(occupations) if is_employed else None,
            'is_student': random.choice([True, False]) if age < 25 else False,
            'is_solo_parent': random.choice([True, False]) if age > 20 else False,
            'is_pwd': is_pwd,
            'disability_type': random.choice(disability_types) if is_pwd else None,
            'family_income': family_income
        })
    
    connection.commit()
    print(f"✅ Created {len(created_users)} community users\n")
    
    # Create applications with time series data
    print("📝 Creating applications with time-series data...")
    
    if not created_users:
        print("⚠️  No users created. Skipping applications.")
        return
    
    applications_created = 0
    
    # Generate 24 months of continuous data (Jan 2024 - Dec 2025)
    months_data = []
    for year in [2024, 2025]:
        month_range = range(1, 13)  # All 12 months for both years
        for month in month_range:
            months_data.append((year, month))
    
    base_applications = 3
    status_choices = ['pending', 'approved', 'rejected', 'active', 'completed']
    
    for idx, (year, month) in enumerate(months_data):
        # Trend and seasonality
        trend = int(idx * 0.2)
        
        if month in [6, 7, 8]:
            seasonality = 2
        elif month in [12, 1, 2]:
            seasonality = -1
        else:
            seasonality = 0
        
        noise = random.randint(-1, 1)
        num_apps_this_month = max(2, base_applications + trend + seasonality + noise)
        
        # Determine last day of month
        if month in [1, 3, 5, 7, 8, 10, 12]:
            last_day = 31
        elif month in [4, 6, 9, 11]:
            last_day = 30
        else:
            last_day = 29 if year == 2024 else 28
        
        # Create applications
        for _ in range(num_apps_this_month):
            user_id = random.choice(created_users)
            program_id = random.choice(program_ids)
            
            day = random.randint(1, last_day)
            hour = random.randint(8, 17)
            minute = random.randint(0, 59)
            application_date = datetime(year, month, day, hour, minute)
            
            # Status distribution using weighted selection
            status_weights = [0.30, 0.25, 0.10, 0.20, 0.15]
            application_status = np.random.choice(status_choices, p=status_weights)
            
            # Determine claim status based on application status
            if application_status == 'active':
                document_upload_status = random.choice(['uploaded', 'verified', 'pending'])
                claim_status = 'not_scheduled'
            elif application_status == 'approved':
                document_upload_status = 'pending'
                claim_status = 'not_scheduled'
            elif application_status == 'completed':
                document_upload_status = 'verified'
                claim_status = random.choice(['scheduled', 'claimed', 'missed'])
            else:
                document_upload_status = 'pending'
                claim_status = 'not_scheduled'
            
            # Generate verification code if active/approved
            verification_code = None
            if application_status in ['approved', 'active'] and random.random() < 0.5:
                verification_code = ''.join(random.choices('0123456789', k=6))
            
            # Prepare claim data if needed
            claim_date = None
            claim_time = None
            if claim_status in ['scheduled', 'claimed', 'missed']:
                claim_date = application_date + timedelta(days=random.randint(7, 60))
                claim_time = random.choice(['09:00 AM', '10:00 AM', '01:00 PM', '02:00 PM', '03:00 PM'])
            
            insert_app_query = sa.text("""
                INSERT INTO applications (
                    user_id, program_id, application_date, application_status,
                    document_upload_status, claim_status, verification_code,
                    claim_date, claim_time, claim_location, claim_scheduled_by, claim_scheduled_at
                ) VALUES (
                    :user_id, :program_id, :application_date, :application_status,
                    :document_upload_status, :claim_status, :verification_code,
                    :claim_date, :claim_time, :claim_location, :claim_scheduled_by, :claim_scheduled_at
                )
            """)
            
            connection.execute(insert_app_query, {
                'user_id': user_id,
                'program_id': program_id,
                'application_date': application_date,
                'application_status': application_status,
                'document_upload_status': document_upload_status,
                'claim_status': claim_status,
                'verification_code': verification_code,
                'claim_date': claim_date,
                'claim_time': claim_time,
                'claim_location': 'MSWD Office, Mabitac Municipal Hall',
                'claim_scheduled_by': admin_id if claim_status in ['scheduled', 'claimed', 'missed'] else None,
                'claim_scheduled_at': application_date + timedelta(days=random.randint(1, 5)) if claim_status in ['scheduled', 'claimed', 'missed'] else None
            })
            
            applications_created += 1
    
    connection.commit()
    print(f"✅ Created {applications_created} applications\n")
    print("🎉 Dummy data migration completed successfully!")


def downgrade():
    """Remove test data"""
    
    connection = op.get_bind()
    
    print("🧹 Removing dummy data...")
    
    # Get admin user to identify test users
    admin_result = connection.execute(sa.text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))
    admin_row = admin_result.fetchone()
    
    if admin_row:
        admin_id = admin_row[0]
        
        # Delete applications for community users
        delete_apps = sa.text("""
            DELETE FROM applications 
            WHERE user_id IN (SELECT id FROM users WHERE role = 'community' AND email LIKE 'user%@test.com')
        """)
        connection.execute(delete_apps)
        
        # Delete community profiles and users
        delete_community = sa.text("""
            DELETE FROM community_users 
            WHERE user_id IN (SELECT id FROM users WHERE role = 'community' AND email LIKE 'user%@test.com')
        """)
        connection.execute(delete_community)
        
        delete_users = sa.text("""
            DELETE FROM users WHERE role = 'community' AND email LIKE 'user%@test.com'
        """)
        connection.execute(delete_users)
        
        connection.commit()
        print("✅ Dummy data removed successfully!")
