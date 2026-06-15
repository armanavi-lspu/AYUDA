#!/usr/bin/env python
"""Populate 24 months continuous data using raw SQL - faster"""

from app import create_app, db
from datetime import datetime, timedelta
import random
import string
import numpy as np
from sqlalchemy import text

app = create_app()

with app.app_context():
    try:
        connection = db.engine.connect()
        
        # Delete existing test data first
        print("🗑️  Deleting existing test data...")
        delete_apps = text("""
            DELETE FROM applications 
            WHERE user_id IN (
                SELECT id FROM users WHERE role = 'community' AND email LIKE 'user%@test.com'
            )
        """)
        connection.execute(delete_apps)
        
        delete_comm = text("""
            DELETE FROM community_users 
            WHERE user_id IN (
                SELECT id FROM users WHERE role = 'community' AND email LIKE 'user%@test.com'
            )
        """)
        connection.execute(delete_comm)
        
        delete_users = text("""
            DELETE FROM users  
            WHERE role = 'community' AND email LIKE 'user%@test.com'
        """)
        connection.execute(delete_users)
        connection.commit()
        print("✅ Cleaned existing test data\n")
        
        # Get admin and programs
        admin_result = connection.execute(text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))
        admin_id = admin_result.scalar()
        
        programs_result = connection.execute(text("SELECT id FROM programs LIMIT 20"))
        program_ids = [row[0] for row in programs_result.fetchall()]
        
        print(f"✅ Found admin ID: {admin_id}, {len(program_ids)} programs\n")
        
        # Data pools
        barangays = ['Amuyong', 'Bayanihan', 'Lambac', 'Libis ng Nayon', 'Lucong', 
                     'Maligaya', 'Masikap', 'Matalatala', 'Nanguma', 'Numero Uno']
        occupations = ['Farmer', 'Driver', 'Store Owner', 'Teacher', 'Security Guard']
        disability_types = ['Visual Impairment', 'Hearing Impairment', 'Physical Disability']
        
        # Create 20 test users quickly
        print("👥 Creating 20 test users...")
        for i in range(20):
            email = f'user{i+21}@test.com'
            
            # Pre-computed password hash (same for all for speed)
            password_hash = 'pbkdf2:sha256$260000$SomeRandomSalt$SomeHashValue'
            
            insert_user = text("""
                INSERT INTO users (email, password_hash, first_name, last_name, role, created_at)
                VALUES (:email, :hash, :fname, :lname, 'community', NOW())
            """)
            connection.execute(insert_user, {
                'email': email,
                'hash': password_hash,
                'fname': f'User{i+21}',
                'lname': 'Test'
            })
        
        connection.commit()
        print("✅ Created 20 test users\n")
        
        # Get created user IDs
        user_ids_result = connection.execute(text("""
            SELECT id FROM users 
            WHERE role = 'community' AND email LIKE 'user%@test.com'
            ORDER BY created_at
        """))
        user_ids = [row[0] for row in user_ids_result.fetchall()]
        print(f"✅ Got {len(user_ids)} user IDs\n")
        
        # Create CommunityUsers profiles with essential demographic info
        print("👤 Creating community user profiles with demographic data...")
        for idx, user_id in enumerate(user_ids):
            age = random.randint(18, 75)
            gender = random.choice(['Male', 'Female', 'Other'])
            mobile_no = f'09{random.randint(100000000, 999999999)}'
            is_employed = random.choice([True, False])
            is_student = random.choice([True, False]) if age < 40 else False
            is_solo_parent = random.choice([True, False])
            is_pwd = random.choice([True, False])
            
            barangay = random.choice(barangays)
            sitio = f'Sitio {chr(65 + random.randint(0, 5))}'
            address = f'{sitio}, {barangay}, Mabitac, Laguna'
            
            family_income = random.randint(20000, 40000)
            
            create_community = text("""
                INSERT INTO community_users (
                    user_id, age, gender, mobile_no, barangay, sitio, address,
                    municipality, is_currently_employed, occupation, is_student,
                    is_solo_parent, is_pwd, disability_type, family_annual_income,
                    created_at
                ) VALUES (
                    :uid, :age, :gender, :mobile, :barangay, :sitio, :address,
                    'Mabitac', :employed, :occupation, :student, :solo_parent, 
                    :pwd, :disability, :income, NOW()
                )
            """)
            
            connection.execute(create_community, {
                'uid': user_id,
                'age': age,
                'gender': gender,
                'mobile': mobile_no,
                'barangay': barangay,
                'sitio': sitio,
                'address': address,
                'employed': is_employed,
                'occupation': random.choice(occupations) if is_employed else None,
                'student': is_student,
                'solo_parent': is_solo_parent,
                'pwd': is_pwd,
                'disability': random.choice(disability_types) if is_pwd else None,
                'income': family_income
            })
        
        connection.commit()
        print(f"✅ Created {len(user_ids)} community user profiles\n")
        
        # Create 24 months of continuous applications (Jan 2024 - Dec 2025)
        print("📝 Creating applications for 24 months (Jan 2024 - Dec 2025)...")
        
        app_count = 0
        base_apps = 3
        
        for year in [2024, 2025]:
            for month in range(1, 13):
                # Calculate number of apps
                trend = int((year-2024)*12 + month) * 0.08
                seasonality = 2 if month in [6,7,8] else (-1 if month in [12,1,2] else 0)
                noise = random.randint(-1, 1)
                num_apps = max(2, int(base_apps + trend + seasonality + noise))
                
                # Days in month
                if month in [1,3,5,7,8,10,12]:
                    last_day = 31
                elif month in [4,6,9,11]:
                    last_day = 30
                else:
                    last_day = 29 if year == 2024 else 28
                
                # Create apps for this month
                for _ in range(num_apps):
                    user_id = random.choice(user_ids)
                    program_id = random.choice(program_ids)
                    day = random.randint(1, last_day)
                    app_date = datetime(year, month, day, random.randint(8, 17), random.randint(0, 59))
                    
                    status = random.choice(['pending', 'approved', 'rejected', 'active', 'completed'])
                    
                    # Generate verification code (uppercase 10-char alphanumeric)
                    verification_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
                    
                    # Submission deadline is 14 days after application
                    submission_deadline = app_date + timedelta(days=14)
                    
                    # Claim location if approved
                    claim_location = "Municipal Office, Mabitac, Laguna 10:00 AM - 3:00 PM"
                    
                    insert_app = text("""
                        INSERT INTO applications (
                            user_id, program_id, application_date, application_status,
                            document_upload_status, claim_status, submission_deadline,
                            verification_code, claim_location
                        ) VALUES (:uid, :pid, :app_date, :status, 'pending', 'not_scheduled',
                                 :deadline, :vcode, :location)
                    """)
                    connection.execute(insert_app, {
                        'uid': user_id,
                        'pid': program_id,
                        'app_date': app_date,
                        'status': status,
                        'deadline': submission_deadline,
                        'vcode': verification_code,
                        'location': claim_location
                    })
                    app_count += 1
        
        connection.commit()
        print(f"✅ Created {app_count} applications\n")
        print("🎉 Data generation completed!")
        
        # Verify
        data_result = connection.execute(text("""
            SELECT DATE_TRUNC('month', application_date), COUNT(*) as cnt
            FROM applications
            GROUP BY DATE_TRUNC('month', application_date)
            ORDER BY DATE_TRUNC('month', application_date)
        """))
        
        print("\n📊 Data Distribution:")
        for row in data_result:
            month_label = row[0].strftime('%B %Y') if row[0] else 'NULL'
            print(f"  {month_label}: {row[1]}")
        
        connection.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
