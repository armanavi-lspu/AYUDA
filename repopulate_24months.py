#!/usr/bin/env python
"""Manually populate dummy data for testing - 24 months continuous"""

from app import create_app, db
from app.models import User, CommunityUsers, Applications, Programs
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash
import random
import numpy as np
from sqlalchemy import func

app = create_app()

with app.app_context():
    try:
        # Check if test users already exist
        test_count = db.session.query(User).filter(
            User.role == 'community',
            User.email.like('user%@test.com')
        ).count()
        
        if test_count > 0:
            print(f"ℹ️  Found {test_count} existing test users. Deleting to regenerate...")
            
            # Delete test data
            db.session.query(Applications).filter(
                Applications.user_id.in_(
                    db.session.query(User.id).filter(
                        User.role == 'community',
                        User.email.like('user%@test.com')
                    )
                )
            ).delete()
            
            db.session.query(CommunityUsers).filter(
                CommunityUsers.user_id.in_(
                    db.session.query(User.id).filter(
                        User.role == 'community',
                        User.email.like('user%@test.com')
                    )
                )
            ).delete()
            
            db.session.query(User).filter(
                User.role == 'community',
                User.email.like('user%@test.com')
            ).delete()
            
            db.session.commit()
            print("✅ Deleted existing test data\n")
        
        # Get admin user
        admin = db.session.query(User).filter(User.role == 'admin').first()
        if not admin:
            print("❌ No admin user found.")
            exit(1)
        
        # Get programs
        programs = db.session.query(Programs).limit(20).all()
        if not programs:
            print("❌ No programs found.")
            exit(1)
        
        print(f"✅ Found {len(programs)} programs\n")
        
        # Demographics data
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
        status_choices = ['pending', 'approved', 'rejected', 'active', 'completed']
        
        # Create 20 test users
        print("👥 Creating 20 community test users...")
        created_users = []
        
        for i in range(20):
            email = f'user{i+21}@test.com'
            
            # Check if already exists
            existing = db.session.query(User).filter(User.email == email).first()
            if existing:
                if existing.role == 'community':
                    created_users.append(existing.id)
                continue
            
            # Create user
            birth_year = random.randint(1960, 2005)
            birth_month = random.randint(1, 12)
            birth_day = random.randint(1, 28)
            
            today = datetime.now()
            age = today.year - birth_year
            if today.month < birth_month or (today.month == birth_month and today.day < birth_day):
                age -= 1
            
            user = User(
                email=email,
                password_hash=generate_password_hash('password123', method='pbkdf2:sha256'),
                first_name=random.choice(first_names),
                middle_name=random.choice(['A', 'B', 'C', 'D', 'E', 'M', 'L', '']),
                last_name=random.choice(last_names),
                role='community',
                created_at=datetime.utcnow()
            )
            db.session.add(user)
            db.session.flush()
            created_users.append(user.id)
            
            # Create community profile 
            is_pwd = True if random.random() < 0.1 else False
            income_bracket = random.random()
            if income_bracket < 0.70:
                family_income = random.randint(30000, 150000)
            elif income_bracket < 0.95:
                family_income = random.randint(150001, 400000)
            else:
                family_income = random.randint(400001, 800000)
            
            community = CommunityUsers(
                user_id=user.id,
                age=age,
                mobile_no=f'09{random.randint(100000000, 999999999)}',
                birth_month=birth_month,
                birth_day=birth_day,
                birth_year=birth_year,
                gender=random.choice(['Male', 'Female', 'Other']),
                barangay=random.choice(barangays),
                sitio=random.choice(sitios),
                address=f'{random.randint(1, 999)} Main St',
                municipality='Mabitac',
                is_currently_employed=random.choice([True, False]),
                occupation=random.choice(occupations) if random.random() < 0.5 else None,
                is_student=random.choice([True, False]) if age < 25 else False,
                is_solo_parent=random.choice([True, False]) if age > 20 else False,
                is_pwd=is_pwd,
                disability_type=random.choice(disability_types) if is_pwd else None,
                family_annual_income=family_income
            )
            db.session.add(community)
        
        db.session.commit()
        print(f"✅ Created {len(created_users)} community users\n")
        
        # Generate 24 months of applications (Jan 2024 - Dec 2025)
        print("📝 Creating applications for 24 months (Jan 2024 - Dec 2025)...")
        
        months_data = []
        for year in [2024, 2025]:
            for month in range(1, 13):
                months_data.append((year, month))
        
        base_applications = 3
        applications_created = 0
        
        for idx, (year, month) in enumerate(months_data):
            # Calculate number of apps for this month
            trend = int(idx * 0.1)
            seasonality = 2 if month in [6, 7, 8] else (-1 if month in [12, 1, 2] else 0)
            noise = random.randint(-1, 1)
            num_apps = max(2, base_applications + trend + seasonality + noise)
            
            # Determine last day of month
            last_day = 31 if month in [1,3,5,7,8,10,12] else (30 if month in [4,6,9,11] else (29 if year == 2024 else 28))
            
            # Create applications for this month
            for _ in range(num_apps):
                user_id = random.choice(created_users)
                program_id = random.choice([p.id for p in programs])
                day = random.randint(1, last_day)
                hour = random.randint(8, 17)
                minute = random.randint(0, 59)
                application_date = datetime(year, month, day, hour, minute)
                
                # Random status
                status_weights = [0.30, 0.25, 0.10, 0.20, 0.15]
                application_status = np.random.choice(status_choices, p=status_weights)
                
                # Determine upload/claim status
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
                
                verification_code = ''.join(random.choices('0123456789', k=6)) if application_status in ['approved', 'active'] and random.random() < 0.5 else None
                
                claim_date = None
                claim_time = None
                if claim_status in ['scheduled', 'claimed', 'missed']:
                    claim_date = application_date + timedelta(days=random.randint(7, 60))
                    claim_time = random.choice(['09:00 AM', '10:00 AM', '01:00 PM', '02:00 PM', '03:00 PM'])
                
                app = Applications(
                    user_id=user_id,
                    program_id=program_id,
                    application_date=application_date,
                    application_status=application_status,
                    document_upload_status=document_upload_status,
                    claim_status=claim_status,
                    verification_code=verification_code,
                    claim_date=claim_date,
                    claim_time=claim_time,
                    claim_location='MSWD Office, Mabitac Municipal Hall',
                    claim_scheduled_by=admin.id if claim_status in ['scheduled', 'claimed', 'missed'] else None,
                    claim_scheduled_at=application_date + timedelta(days=random.randint(1, 5)) if claim_status in ['scheduled', 'claimed', 'missed'] else None
                )
                db.session.add(app)
                applications_created += 1
        
        db.session.commit()
        print(f"✅ Created {applications_created} applications across 24 months\n")
        print("🎉 Dummy data generation completed successfully!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
