"""
Script to populate the database with dummy data for testing analytics and graphs
Run this with: python populate_dummy_data.py
"""

from app import create_app, db
from app.models import User, Programs, Applications, CommunityUsers, AdminUsers, Requirements, ProgramRequirements
from datetime import datetime, timedelta
import random
from werkzeug.security import generate_password_hash

def populate_dummy_data():
    """Populate database with realistic dummy data"""
    
    app = create_app()
    with app.app_context():
        print("🚀 Starting to populate dummy data...\n")
        
        # Clear existing data (optional - comment out if you want to keep existing data)
        print("⚠️  Clearing existing data...")
        Applications.query.delete()
        ProgramRequirements.query.delete()
        Requirements.query.delete()
        CommunityUsers.query.delete()
        AdminUsers.query.delete()
        Programs.query.delete()
        User.query.delete()
        db.session.commit()
        print("✅ Existing data cleared\n")
        
        # 1. Create Admin User
        print("👤 Creating admin user...")
        admin_user = User(
            email='admin@ayuda.com',
            password_hash=generate_password_hash('admin123'),
            first_name='System',
            middle_name='',
            last_name='Administrator',
            role='admin'
        )
        db.session.add(admin_user)
        db.session.commit()
        
        # Create admin profile
        admin_profile = AdminUsers(
            user_id=admin_user.id
        )
        db.session.add(admin_profile)
        db.session.commit()
        print(f"✅ Admin user created: {admin_user.email}\n")
        
        # 2. Create Community Users
        print("👥 Creating community users...")
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
        
        community_users = []
        for i in range(50):  # Create 50 community users
            first_name = random.choice(first_names)
            last_name = random.choice(last_names)
            
            # Generate birth date components
            birth_year = random.randint(1960, 2005)
            birth_month = random.randint(1, 12)
            birth_day = random.randint(1, 28)
            
            # Calculate age
            today = datetime.now()
            age = today.year - birth_year
            if today.month < birth_month or (today.month == birth_month and today.day < birth_day):
                age -= 1
            
            user = User(
                email=f'user{i+1}@test.com',
                password_hash=generate_password_hash('password123'),
                first_name=first_name,
                middle_name=random.choice(['A', 'B', 'C', 'D', 'E', 'M', 'L', '']),
                last_name=last_name,
                role='community'
            )
            db.session.add(user)
            db.session.flush()
            
            # Create community profile matching your model structure
            community_profile = CommunityUsers(
                user_id=user.id,
                age=age,
                mobile_no=f'09{random.randint(100000000, 999999999)}',
                birth_month=birth_month,
                birth_day=birth_day,
                birth_year=birth_year,
                barangay=random.choice(barangays),
                sitio=random.choice(sitios),
                municipality='Mabitac',
                is_currently_employed=random.choice([True, False]),
                is_student=random.choice([True, False]) if age < 25 else False,
                is_solo_parent=random.choice([True, False]) if age > 20 else False,
                family_annual_income=random.randint(50000, 300000)
            )
            db.session.add(community_profile)
            community_users.append(user)
        
        db.session.commit()
        print(f"✅ Created {len(community_users)} community users\n")
        
        # 3. Create Programs
        print("📋 Creating programs...")
        program_data = [
            {
                'name': 'Financial Assistance Program',
                'type': 'AICS',
                'period': 'Ongoing',
                'description': 'Provides financial support to families in need for emergencies and basic necessities'
            },
            {
                'name': 'Burial Assistance Program',
                'type': 'AICS',
                'period': 'Emergency',
                'description': 'Provides financial support to families in need for burial and funeral services'
            },
            {
                'name': 'AKAP Partylist - Educational Assistance Program',
                'type': 'AICS',
                'period': 'Annual',
                'description': 'One time financial assistance program for elementary to college students'
            },
            {
                'name': 'Educational Assistance Program',
                'type': 'AICS',
                'period': 'Semi-Annual',
                'description': 'Educational financial assistance program for elementary to college students'
            },
            {
                'name': 'Medical Assistance Program',
                'type': 'AICS',
                'period': 'Ongoing',
                'description': 'Healthcare support including medicine subsidies, hospital bills, and medical procedures'
            },
            {
                'name': 'Livelihood Development Program',
                'type': 'CAL',
                'period': 'Quarterly',
                'description': 'Skills training and business capital assistance for sustainable income generation'
            },
            {
                'name': 'Fire Disaster',
                'type': 'ESA',
                'period': 'Emergency',
                'description': 'Temporary shelter and housing assistance for families affected by fire incidents'
            },
            {
                'name': 'Typhoon Disaster',
                'type': 'ESA',
                'period': 'Emergency',
                'description': 'Temporary shelter and housing assistance for families affected by typhoon incidents'
            },
            {
                'name': 'Capital Assistance for Livelihood Program',
                'type': 'CAL',
                'period': 'Monthly',
                'description': 'Support for microenterprise development and livelihood projects'
            },            
            {
                'name': 'Christmas Gift Giving Program',
                'type': 'AICS',
                'period': 'Seasonal',
                'description': 'Annual Christmas gift distribution for indigent families'
            },
            {
                'name': 'Back-to-School Assistance',
                'type': 'AICS',
                'period': 'Seasonal',
                'description': 'School supplies and uniform assistance distributed before school opening'
            },
        ]
        
        programs = []
        for prog in program_data:
            program = Programs(
                program_name=prog['name'],
                program_type=prog['type'],
                program_period=prog['period'],
                description=prog['description'],
                user_id=admin_user.id
            )
            db.session.add(program)
            db.session.flush()
            programs.append(program)
        
        db.session.commit()
        print(f"✅ Created {len(programs)} programs\n")
        
        # 4. Create Requirements (Documents and Qualifications)
        print("📋 Creating requirements...")
        
        # Document Requirements
        document_requirements_data = [
            {'name': 'Valid ID', 'description': 'Any government-issued ID (PhilID, Driver\'s License, Passport, etc.)'},
            {'name': 'PSA Birth Certificate', 'description': 'Original copy from PSA (Philippine Statistics Authority)'},
            {'name': 'Certificate of Enrollment', 'description': 'Current certificate of enrollment from school'},
            {'name': 'Certificate of Registration (COR)', 'description': 'Certificate of Registration for current semester'},
            {'name': 'Certificate of Grades (COG)', 'description': 'Latest grades from previous semester'},
            {'name': 'Student ID', 'description': 'Valid student identification card'},
            {'name': 'Barangay Certificate', 'description': 'Certificate of Residency from Barangay'},
            {'name': 'Barangay Indigency Certificate', 'description': 'Certificate of Indigency from Barangay'},
            {'name': 'Barangay Clearance', 'description': 'Barangay clearance certificate'},
            {'name': 'Medical Certificate', 'description': 'Medical certificate from licensed physician'},
            {'name': 'Death Certificate', 'description': 'PSA Death Certificate of deceased'},
            {'name': 'Proof of Income', 'description': 'Latest payslip, ITR, or certificate of income'},
            {'name': 'Funeral Contract', 'description': 'Contract or agreement with funeral service provider'},
            {'name': 'Hospital Bills/Medical Records', 'description': 'Medical bills, prescriptions, or hospital records'},
            {'name': 'PWD ID', 'description': 'Valid Person with Disability identification card'},
            {'name': 'Senior Citizen ID', 'description': 'Valid senior citizen identification card'},
            {'name': 'Solo Parent ID', 'description': 'Valid solo parent identification card'},
            {'name': '2x2 ID Picture', 'description': 'Recent 2x2 identification picture'},
            {'name': 'Proof of Business', 'description': 'Business permit, DTI registration, or business-related documents'},
        ]
        
        document_requirements = []
        for req_data in document_requirements_data:
            req = Requirements(
                requirement_name=req_data['name'],
                requirement_type='document',
                description=req_data['description']
            )
            db.session.add(req)
            db.session.flush()
            document_requirements.append(req)
        
        # Qualification Requirements
        qualification_requirements_data = [
            {'name': 'Student', 'description': 'Currently enrolled in any educational institution'},
            {'name': 'Solo Parent', 'description': 'Registered solo parent with valid ID'},
            {'name': 'Low Income Family', 'description': 'Family annual income below poverty threshold'},
            {'name': 'Indigent Family', 'description': 'Family identified as indigent by barangay'},
            {'name': 'Person with Disability (PWD)', 'description': 'Registered PWD with valid ID'},
            {'name': 'Senior Citizen', 'description': '60 years old and above with valid ID'},
            {'name': 'Unemployed', 'description': 'Currently unemployed and seeking livelihood'},
            {'name': 'Resident of Mabitac', 'description': 'Bonafide resident of Mabitac, Laguna'},
            {'name': 'Fire Victim', 'description': 'Affected by fire incident (with barangay certification)'},
            {'name': 'Typhoon Victim', 'description': 'Affected by typhoon/calamity (with barangay certification)'},
            {'name': 'Family Member of Deceased', 'description': 'Immediate family member of the deceased'},
            {'name': 'Medical Emergency', 'description': 'Experiencing medical emergency or critical illness'},
        ]
        
        qualification_requirements = []
        for req_data in qualification_requirements_data:
            req = Requirements(
                requirement_name=req_data['name'],
                requirement_type='qualification',
                description=req_data['description']
            )
            db.session.add(req)
            db.session.flush()
            qualification_requirements.append(req)
        
        db.session.commit()
        print(f"✅ Created {len(document_requirements)} document requirements")
        print(f"✅ Created {len(qualification_requirements)} qualification requirements\n")
        
        # 5. Assign Requirements to Programs
        print("🔗 Assigning requirements to programs...")
        
        # Helper function to find requirement by name
        def find_doc(name):
            return next((r for r in document_requirements if r.requirement_name == name), None)
        
        def find_qual(name):
            return next((r for r in qualification_requirements if r.requirement_name == name), None)
        
        # Program-specific requirements mapping
        program_requirements_mapping = {
            'Financial Assistance Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Barangay Certificate', True),
                    ('Barangay Indigency Certificate', True),
                    ('Proof of Income', True),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Burial Assistance Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Death Certificate', True),
                    ('Funeral Contract', True),
                    ('Barangay Certificate', True),
                    ('Barangay Indigency Certificate', False),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Family Member of Deceased', True),
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'AKAP Partylist - Educational Assistance Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Student ID', True),
                    ('Certificate of Enrollment', True),
                    ('Certificate of Registration (COR)', True),
                    ('Certificate of Grades (COG)', False),
                    ('Barangay Certificate', True),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Student', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Educational Assistance Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Student ID', True),
                    ('Certificate of Enrollment', True),
                    ('Certificate of Registration (COR)', True),
                    ('Certificate of Grades (COG)', True),
                    ('Barangay Certificate', True),
                    ('Barangay Indigency Certificate', True),
                    ('Proof of Income', False),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Student', True),
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Medical Assistance Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Medical Certificate', True),
                    ('Hospital Bills/Medical Records', True),
                    ('Barangay Certificate', True),
                    ('Barangay Indigency Certificate', True),
                    ('Proof of Income', False),
                    ('PWD ID', False),
                    ('Senior Citizen ID', False),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Medical Emergency', True),
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Livelihood Development Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Barangay Certificate', True),
                    ('Barangay Clearance', True),
                    ('Proof of Income', False),
                    ('Proof of Business', False),
                    ('2x2 ID Picture', True),
                ],
                'qualifications': [
                    ('Unemployed', True),
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Fire Disaster': {
                'documents': [
                    ('Valid ID', True),
                    ('Barangay Certificate', True),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Fire Victim', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Typhoon Disaster': {
                'documents': [
                    ('Valid ID', True),
                    ('Barangay Certificate', True),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Typhoon Victim', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Capital Assistance for Livelihood Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Barangay Certificate', True),
                    ('Barangay Clearance', True),
                    ('Proof of Business', True),
                    ('Proof of Income', False),
                    ('2x2 ID Picture', True),
                ],
                'qualifications': [
                    ('Unemployed', False),
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Senior Citizen Support Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Senior Citizen ID', True),
                    ('Barangay Certificate', True),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Senior Citizen', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Christmas Gift Giving Program': {
                'documents': [
                    ('Valid ID', True),
                    ('Barangay Certificate', True),
                    ('Barangay Indigency Certificate', True),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
            'Back-to-School Assistance': {
                'documents': [
                    ('Valid ID', True),
                    ('Student ID', True),
                    ('Certificate of Enrollment', True),
                    ('Barangay Certificate', True),
                    ('2x2 ID Picture', False),
                ],
                'qualifications': [
                    ('Student', True),
                    ('Low Income Family', True),
                    ('Resident of Mabitac', True),
                ]
            },
        }
        
        # Assign requirements to each program
        requirements_assigned = 0
        for program in programs:
            if program.program_name in program_requirements_mapping:
                mapping = program_requirements_mapping[program.program_name]
                
                # Assign document requirements
                for doc_name, is_mandatory in mapping['documents']:
                    doc_req = find_doc(doc_name)
                    if doc_req:
                        prog_req = ProgramRequirements(
                            program_id=program.id,
                            requirement_id=doc_req.id,
                            is_mandatory=is_mandatory
                        )
                        db.session.add(prog_req)
                        requirements_assigned += 1
                
                # Assign qualification requirements
                for qual_name, is_mandatory in mapping['qualifications']:
                    qual_req = find_qual(qual_name)
                    if qual_req:
                        prog_req = ProgramRequirements(
                            program_id=program.id,
                            requirement_id=qual_req.id,
                            is_mandatory=is_mandatory
                        )
                        db.session.add(prog_req)
                        requirements_assigned += 1
        
        db.session.commit()
        print(f"✅ Assigned {requirements_assigned} requirements to programs\n")
        
        # 6. Create Applications (distributed from January to October)
        print("📝 Creating applications (January - October 2025)...")
        statuses = ['pending', 'approved', 'rejected', 'under_review', 'on-hold']
        status_weights = [0.35, 0.40, 0.10, 0.10, 0.05]  # Probability weights
        
        applications_created = 0
        current_year = 2025
        
        # Create applications from January to October
        for month in range(1, 11):  # January (1) to October (10)
            # Define month boundaries
            start_date = datetime(current_year, month, 1)
            
            # Get last day of month
            if month in [1, 3, 5, 7, 8, 10]:
                last_day = 31
            elif month in [4, 6, 9]:
                last_day = 30
            else:  # February
                last_day = 28
            
            end_date = datetime(current_year, month, last_day, 23, 59, 59)
            days_in_month = last_day
            
            # Vary applications per month (more in recent months)
            if month >= 8:  # August to October
                num_applications = random.randint(18, 28)
            elif month >= 5:  # May to July
                num_applications = random.randint(12, 22)
            else:  # January to April
                num_applications = random.randint(8, 15)
            
            for _ in range(num_applications):
                user = random.choice(community_users)
                program = random.choice(programs)
                
                # Random date within the month
                days_offset = random.randint(0, days_in_month - 1)
                hours_offset = random.randint(8, 17)  # Business hours
                minutes_offset = random.randint(0, 59)
                
                application_date = start_date + timedelta(
                    days=days_offset,
                    hours=hours_offset,
                    minutes=minutes_offset
                )
                
                # Create application
                status = random.choices(statuses, weights=status_weights)[0]
                
                application = Applications(
                    user_id=user.id,
                    program_id=program.id,
                    application_date=application_date,
                    application_status=status
                )
                
                # Add review info if approved or rejected
                if status in ['approved', 'rejected', 'under_review', 'on-hold']:
                    application.reviewed_by = admin_user.id
                    review_days = random.randint(3, 14)
                    application.review_date = application_date + timedelta(days=review_days)
                    
                    if status == 'approved':
                        application.remarks = 'Application meets all requirements and is approved.'
                    else:
                        application.remarks = 'Incomplete documents or does not meet eligibility criteria.'
                
                db.session.add(application)
                applications_created += 1
        
        db.session.commit()
        print(f"✅ Created {applications_created} applications (January - October {current_year})\n")
        
        # Print summary
        print("="*70)
        print("📊 DATA SUMMARY")
        print("="*70)
        print(f"✅ Admin Users: 1")
        print(f"✅ Community Users: {len(community_users)}")
        print(f"✅ Programs: {len(programs)}")
        print(f"✅ Document Requirements: {len(document_requirements)}")
        print(f"✅ Qualification Requirements: {len(qualification_requirements)}")
        print(f"✅ Program-Requirement Assignments: {requirements_assigned}")
        print(f"✅ Applications: {applications_created}")
        print(f"✅ Barangays: {len(barangays)}")
        print("="*70)
        
        # Show statistics
        print("\n📈 APPLICATION STATISTICS:")
        for status in statuses:
            count = Applications.query.filter_by(application_status=status).count()
            percentage = (count / applications_created * 100) if applications_created > 0 else 0
            print(f"   • {status.upper()}: {count} ({percentage:.1f}%)")
        
        print("\n📅 MONTHLY APPLICATION DISTRIBUTION:")
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
        for month in range(1, 11):
            count = Applications.query.filter(
                db.func.extract('month', Applications.application_date) == month,
                db.func.extract('year', Applications.application_date) == current_year
            ).count()
            print(f"   • {month_names[month-1]} {current_year}: {count} applications")
        
        print("\n🏘️  TOP BARANGAYS BY APPLICATION COUNT:")
        barangay_counts = {}
        for barangay in barangays:
            count = db.session.query(Applications).join(
                User, Applications.user_id == User.id
            ).join(
                CommunityUsers, User.id == CommunityUsers.user_id
            ).filter(CommunityUsers.barangay == barangay).count()
            barangay_counts[barangay] = count
        
        sorted_barangays = sorted(barangay_counts.items(), key=lambda x: x[1], reverse=True)
        for barangay, count in sorted_barangays[:8]:
            print(f"   • {barangay}: {count} applications")
        
        print("\n📋 PROGRAM TYPE DISTRIBUTION:")
        program_type_counts = {}
        for program in programs:
            count = Applications.query.filter_by(program_id=program.id).count()
            if program.program_type not in program_type_counts:
                program_type_counts[program.program_type] = 0
            program_type_counts[program.program_type] += count
        
        for prog_type, count in sorted(program_type_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / applications_created * 100) if applications_created > 0 else 0
            print(f"   • {prog_type}: {count} applications ({percentage:.1f}%)")
        
        print("\n👥 USER DEMOGRAPHICS:")
        employed_count = CommunityUsers.query.filter_by(is_currently_employed=True).count()
        student_count = CommunityUsers.query.filter_by(is_student=True).count()
        solo_parent_count = CommunityUsers.query.filter_by(is_solo_parent=True).count()
        print(f"   • Employed: {employed_count}")
        print(f"   • Students: {student_count}")
        print(f"   • Solo Parents: {solo_parent_count}")
        
        from sqlalchemy import func
        avg_income = db.session.query(func.avg(CommunityUsers.family_annual_income)).scalar()
        print(f"   • Average Family Income: ₱{avg_income:,.2f}")
        
        print("\n📋 REQUIREMENTS BREAKDOWN:")
        print(f"   • Total Document Requirements: {len(document_requirements)}")
        print(f"   • Total Qualification Requirements: {len(qualification_requirements)}")
        
        print("\n📑 SAMPLE PROGRAM REQUIREMENTS:")
        sample_programs = ['Educational Assistance Program', 'Medical Assistance Program', 'Fire Disaster']
        for prog_name in sample_programs:
            program = next((p for p in programs if p.program_name == prog_name), None)
            if program:
                prog_reqs = ProgramRequirements.query.filter_by(program_id=program.id).all()
                doc_count = sum(1 for pr in prog_reqs if pr.requirement.requirement_type == 'document')
                qual_count = sum(1 for pr in prog_reqs if pr.requirement.requirement_type == 'qualification')
                mandatory_count = sum(1 for pr in prog_reqs if pr.is_mandatory)
                print(f"   • {prog_name}:")
                print(f"     - Documents: {doc_count}, Qualifications: {qual_count}")
                print(f"     - Mandatory: {mandatory_count}, Optional: {len(prog_reqs) - mandatory_count}")
        
        print("\n" + "="*70)
        print("🎉 Dummy data population completed successfully!")
        print("="*70)
        print("\n📝 Login credentials:")
        print("   Admin: admin@ayuda.com / admin123")
        print("   Users: user1@test.com to user50@test.com / password123")
        print("\n💡 Tip: Navigate to Analytics → Analysis to view the graphs!")
        print("\n")

if __name__ == '__main__':
    populate_dummy_data()