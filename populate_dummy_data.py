"""
Script to populate the database with dummy data for testing analytics and graphs
Run this with: python populate_dummy_data.py
"""

from app import create_app, db
from app.models import (User, Programs, Applications, CommunityUsers, AdminUsers, Requirements, 
                       ProgramRequirements, ShelterPhotos, ProgramWorkflowSteps, 
                       ApplicationDocuments, ApplicationDocumentUploads, CALDocuments,
                       Announcements, Notifications)
from datetime import datetime, timedelta
import random
import numpy as np
from werkzeug.security import generate_password_hash
from sqlalchemy import func

def populate_dummy_data():
    """Populate database with realistic dummy data"""
    
    app = create_app()
    
    with app.app_context():
        try:
            print("Starting to populate dummy data...\n")
            
            # Clear existing data (optional - comment out if you want to keep existing data)
            print("⚠️  Clearing existing data...")
            try:
                # Clear in proper order to respect foreign key constraints
                CALDocuments.query.delete()
                ApplicationDocumentUploads.query.delete()
                ApplicationDocuments.query.delete()
                ShelterPhotos.query.delete()
                ProgramWorkflowSteps.query.delete()
                Notifications.query.delete()
                Announcements.query.delete()
                Applications.query.delete()
                ProgramRequirements.query.delete()
                Requirements.query.delete()
                CommunityUsers.query.delete()
                AdminUsers.query.delete()
                Programs.query.delete()                
                User.query.delete()
                db.session.commit()
                print("✅ Existing data cleared\n")
            except Exception as e:
                print(f"⚠️  Warning: Could not clear all existing data: {e}")
                db.session.rollback()
                print("   Continuing with population...\n")
            
            # 1. Create Admin User
            print("👤 Creating admin user...")
            admin_user = User(
                email='MSWDMabitac@gmail.com',
                password_hash=generate_password_hash('MabitacMSWD_2025'),
                first_name='MSWD',
                middle_name='',
                last_name='Mabitac',
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
            for i in range(20):  # Create 20 community users (reduced from 50)
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
                
                # Determine gender
                gender = random.choice(['Male', 'Female', 'Other'])
                
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
                
                # Generate occupation if employed
                occupations = ['Farmer', 'Driver', 'Store Owner', 'Teacher', 'Security Guard', 
                              'Factory Worker', 'Carpenter', 'Electrician', 'Unemployed']
                is_employed = random.choice([True, False])
                occupation = random.choice(occupations) if is_employed else 'Unemployed'
                
                # Check disability status and type
                is_pwd = random.choice([True, False]) if random.random() < 0.1 else False
                disability_types = ['Visual Impairment', 'Hearing Impairment', 'Physical Disability', 
                                   'Mental/Psychosocial', 'Speech Impairment']
                disability_type = random.choice(disability_types) if is_pwd else None
                
                # Generate family annual income within valid range (0 - 10,000,000)
                # Most families: 30,000 - 300,000
                # Low-income families (70%): 30,000 - 150,000
                # Middle-income families (25%): 150,001 - 400,000
                # Higher-income families (5%): 400,001 - 800,000
                income_bracket = random.random()
                if income_bracket < 0.70:
                    family_income = random.randint(30000, 150000)
                elif income_bracket < 0.95:
                    family_income = random.randint(150001, 400000)
                else:
                    family_income = random.randint(400001, 800000)
                
                # Create community profile matching updated model structure
                community_profile = CommunityUsers(
                    user_id=user.id,
                    age=age,
                    mobile_no=f'09{random.randint(100000000, 999999999)}',
                    birth_month=birth_month,
                    birth_day=birth_day,
                    birth_year=birth_year,
                    gender=gender,
                    barangay=random.choice(barangays),
                    sitio=random.choice(sitios),
                    address=f'{random.randint(1, 999)} Main St, {random.choice(sitios)}',
                    municipality='Mabitac',
                    is_currently_employed=is_employed,
                    occupation=occupation,
                    is_student=random.choice([True, False]) if age < 25 else False,
                    is_solo_parent=random.choice([True, False]) if age > 20 else False,
                    is_pwd=is_pwd,
                    disability_type=disability_type,
                    family_annual_income=family_income
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
                    'name': 'Capital Assistance Program',
                    'type': 'CA',
                    'period': 'Monthly',
                    'description': 'Support for microenterprise development and livelihood projects'
                },                            
            ]
            
            programs = []
            for prog in program_data:
                # Generate random program details
                start_date = datetime.now().date() - timedelta(days=random.randint(30, 365))
                end_date = start_date + timedelta(days=random.randint(90, 730)) if random.random() < 0.7 else None
                
                program = Programs(
                    program_name=prog['name'],
                    program_type=prog['type'],
                    program_period=prog['period'],
                    description=prog['description'],
                    priority_group=random.choice([
                        'Low Income Families', 'Students', 'PWDs, Solo Parents',
                        'Senior Citizens', 'Fire Victims', 'Typhoon Victims',
                        'Unemployed Individuals', 'Small Business Owners'
                    ]),
                    beneficiary_limit=random.choice([None, 50, 100, 150, 200]) if random.random() < 0.6 else None,
                    income_range=random.choice([
                        'Below 50,000', '50,000 - 100,000', '100,000 - 200,000', 
                        'Below 150,000', 'Any Income Level'
                    ]),
                    start_date=start_date,
                    end_date=end_date,
                    user_id=admin_user.id,
                    is_active=random.choice([True, True, True, False]),  # 75% active
                    allow_online_upload=random.choice([True, True, False])  # 67% allow online upload
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
                {'name': 'PSA Birth Certificate', 'description': 'Photocopy of birth certificate from PSA (Philippine Statistics Authority)'},
                {'name': 'Certificate of Enrollment / Registration (COR)', 'description': 'Current certificate of enrollment/registration from school for current semester/quarter'},
                {'name': 'Certificate of Grades (COG)', 'description': 'Latest grades from previous semester/quarter'},
                {'name': 'Student ID', 'description': 'Valid student identification card issued by the current school (School ID)'},
                {'name': 'Barangay Report', 'description': 'Barangay report for disaster-affected applicants'},
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
                {'name': 'Resident of Mabitac', 'description': 'Bonafide resident of Mabitac, Laguna'},
                {'name': 'Fire Victim', 'description': 'Affected by fire incident (with barangay report)'},
                {'name': 'Typhoon Victim', 'description': 'Affected by typhoon/calamity (with barangay report)'},
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
                        ('Barangay Indigency Certificate', True),
                        ('Proof of Income', True),
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
                        ('Barangay Indigency Certificate', False),
                    ],
                    'qualifications': [
                        ('Low Income Family', True),
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
                        ('Barangay Indigency Certificate', True),
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
                        ('Barangay Indigency Certificate', True),
                        ('Proof of Income', False),
                    ],
                    'qualifications': [
                        ('Low Income Family', True),
                        ('Resident of Mabitac', True),
                    ]
                },
                
                'Fire Disaster': {
                    'documents': [
                        ('Valid ID', True),
                        ('Barangay Report', True),
                    ],
                    'qualifications': [
                        ('Fire Victim', True),
                        ('Resident of Mabitac', True),
                    ]
                },
                'Typhoon Disaster': {
                    'documents': [
                        ('Valid ID', True),
                        ('Barangay Report', True),
                    ],
                    'qualifications': [
                        ('Typhoon Victim', True),
                        ('Resident of Mabitac', True),
                    ]
                },
                'Capital Assistance Program': {
                    'documents': [
                        ('Valid ID', True),
                        ('Barangay Clearance', True),
                        ('Proof of Business', True),
                        ('Proof of Income', False),
                    ],
                    'qualifications': [
                        ('Unemployed', False),
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
            
            # 6. Create Applications with time series data for ARIMA forecasting
            # Generate 18 months of data (Jan 2024 - Jun 2025) to ensure ARIMA works
            # ARIMA requires at least 12 continuous months of data
            print("📝 Creating applications with time series data for ARIMA...")

            applications_created = 0
            # Generate monthly data from January 2024 to June 2025 (18 months)
            # This ensures ARIMA has sufficient data points (>= 12 months)
            months_data = []
            for year in [2024, 2025]:
                month_range = range(1, 13) if year == 2024 else range(1, 7)  # Jan-Dec 2024, Jan-Jun 2025
                for month in month_range:
                    months_data.append((year, month))
            
            # Base applications per month with trend and seasonality for ARIMA to detect
            # Trend: gradual increase over time
            # Seasonality: higher in school months (Jun-Aug), lower in Dec-Feb
            base_applications = 3  # Base value for calculations (minimum enforced at 2)
            
            for idx, (year, month) in enumerate(months_data):
                # Trend component: increases over time (0.2 per month)
                trend = int(idx * 0.2)
                
                # Seasonality component: simulate real patterns
                # Higher in June-August (school-related programs)
                # Lower in December-February (holiday/new year)
                if month in [6, 7, 8]:
                    seasonality = 2  # Peak season
                elif month in [12, 1, 2]:
                    seasonality = -1  # Low season
                else:
                    seasonality = 0  # Normal
                
                # Random variation (small noise)
                noise = random.randint(-1, 1)
                
                # Calculate applications for this month (minimum 2)
                num_apps_this_month = max(2, base_applications + trend + seasonality + noise)

                # Last day of month
                if month in [1, 3, 5, 7, 8, 10, 12]:
                    last_day = 31
                elif month in [4, 6, 9, 11]:
                    last_day = 30
                else:  # Feb
                    last_day = 29 if year == 2024 else 28  # 2024 is leap year

                # Create applications for this month
                for _ in range(num_apps_this_month):
                    user = random.choice(community_users)
                    program = random.choice(programs)

                    # Random business-time application within the month
                    day = random.randint(1, last_day)
                    hour = random.randint(8, 17)
                    minute = random.randint(0, 59)
                    application_date = datetime(year, month, day, hour, minute)
                    
                    # Status distribution
                    status_choices = ['pending', 'approved', 'rejected', 'under_review']
                    status_weights = [0.40, 0.30, 0.10, 0.20]
                    application_status = np.random.choice(status_choices, p=status_weights)

                    # Create application with new fields
                    document_upload_status = 'pending'
                    claim_status = 'not_scheduled'
                
                    # Set document upload status based on application status
                    if application_status == 'approved':
                        document_upload_status = random.choice(['uploaded', 'verified', 'pending'])
                        if random.random() < 0.3:  # 30% chance to have claim scheduled
                            claim_status = random.choice(['scheduled', 'claimed', 'missed'])
                    elif application_status == 'under_review':
                        document_upload_status = random.choice(['uploaded', 'pending'])
                    
                    application = Applications(
                        user_id=user.id,
                        program_id=program.id,
                        application_date=application_date,
                        application_status=application_status,
                        document_upload_status=document_upload_status,
                        claim_status=claim_status
                )
                
                # Add submission deadline for some applications
                if random.random() < 0.6:  # 60% have deadline
                    application.submission_deadline = application_date + timedelta(days=random.randint(7, 30))
                
                # Add claim scheduling for approved applications
                if claim_status in ['scheduled', 'claimed', 'missed']:
                    application.claim_date = application_date + timedelta(days=random.randint(7, 60))
                    application.claim_time = random.choice(['09:00 AM', '10:00 AM', '01:00 PM', '02:00 PM', '03:00 PM'])
                    application.claim_location = 'MSWD Office, Mabitac Municipal Hall'
                    application.claim_instructions = 'Please bring valid ID and verification code.'
                    application.claim_scheduled_by = admin_user.id
                    application.claim_scheduled_at = application_date + timedelta(days=random.randint(1, 5))
                
                # Add verification code for some approved applications
                if application_status == 'approved' and random.random() < 0.5:
                    application.generate_verification_code()
                
                db.session.add(application)
                applications_created += 1

            db.session.commit()
            print(f"✅ Created {applications_created} applications\n")
            
            # 7. Create Announcements
            print("📢 Creating announcements...")
            announcement_data = [
                {
                    'title': 'New Educational Assistance Program Now Open',
                    'content': 'The Municipality of Mabitac is now accepting applications for the Educational Assistance Program for the academic year 2025-2026. This program provides financial support to students from kindergarten to college level.',
                    'category': 'Programs',
                    'program_id': next((p.id for p in programs if 'Educational' in p.program_name), None)
                },
                {
                    'title': 'Medical Assistance Available for Senior Citizens',
                    'content': 'Senior citizens of Mabitac can now apply for medical assistance to help cover hospital bills, medicine costs, and medical procedures. Bring your senior citizen ID and medical documents.',
                    'category': 'Healthcare',
                    'program_id': next((p.id for p in programs if 'Medical' in p.program_name), None)
                },
                {
                    'title': 'Important: Document Submission Guidelines',
                    'content': 'All applicants must submit complete documents within 15 days of application approval. Incomplete submissions will result in application cancellation.',
                    'category': 'Guidelines',
                    'program_id': None
                },
                {
                    'title': 'Capital Assistance for Small Business Owners',
                    'content': 'The Capital Assistance Program is now accepting applications from aspiring and existing small business owners. Get financial support for your livelihood projects and microenterprises.',
                    'category': 'Livelihood',
                    'program_id': next((p.id for p in programs if 'Capital' in p.program_name), None)
                },
                {
                    'title': 'Emergency Shelter Assistance Information',
                    'content': 'Families affected by fire or natural disasters can apply for Emergency Shelter Assistance. This program provides temporary housing support and basic necessities.',
                    'category': 'Emergency',
                    'program_id': next((p.id for p in programs if 'Fire' in p.program_name or 'Typhoon' in p.program_name), None)
                }
            ]
            
            announcements = []
            for ann_data in announcement_data:
                announcement = Announcements(
                    announcement_title=ann_data['title'],
                    announcement_content=ann_data['content'],
                    category=ann_data['category'],
                    status=random.choice(['published', 'published', 'draft']),  # 67% published
                    author_id=admin_user.id,
                    program_id=ann_data['program_id'],
                    attachment_url=f'https://mabitac.gov.ph/programs/{ann_data["category"].lower()}' if random.random() < 0.3 else None,
                    created_at=datetime.now() - timedelta(days=random.randint(1, 30))
                )
                db.session.add(announcement)
                db.session.flush()
                announcements.append(announcement)
            
            db.session.commit()
            print(f"✅ Created {len(announcements)} announcements\n")
            
            # 8. Create Notifications
            print("🔔 Creating notifications...")
            notifications_created = 0
            
            # Create notifications for some users
            sample_users = random.sample(community_users, min(10, len(community_users)))
            
            notification_templates = [
                {
                    'title': 'Application Approved',
                    'message': 'Your application for {program} has been approved. Please submit your documents within 15 days.',
                    'related_type': 'application'
                },
                {
                    'title': 'Documents Required',
                    'message': 'Please submit the required documents for your {program} application.',
                    'related_type': 'application'
                },
                {
                    'title': 'New Program Available',
                    'message': 'A new program "{program}" is now available. Check if you qualify!',
                    'related_type': 'program'
                },
                {
                    'title': 'Profile Update Required',
                    'message': 'Please complete your profile information to ensure accurate program recommendations.',
                    'related_type': 'profile'
                },
                {
                    'title': 'Claim Schedule',
                    'message': 'Your assistance claim has been scheduled. Please check your schedule for details.',
                    'related_type': 'schedule'
                }
            ]
            
            for user in sample_users:
                # Create 1-3 notifications per user
                num_notifications = random.randint(1, 3)
                for _ in range(num_notifications):
                    template = random.choice(notification_templates)
                    
                    # Get user's applications for realistic notifications
                    user_applications = Applications.query.filter_by(user_id=user.id).all()
                    if user_applications and template['related_type'] == 'application':
                        app = random.choice(user_applications)
                        related_id = app.id
                        message = template['message'].format(program=app.program.program_name)
                    elif template['related_type'] == 'program':
                        program = random.choice(programs)
                        related_id = program.id
                        message = template['message'].format(program=program.program_name)
                    else:
                        related_id = None
                        message = template['message']
                    
                    notification = Notifications(
                        user_id=user.id,
                        notif_title=template['title'],
                        notif_message=message,
                        is_read=random.choice([True, False]),
                        related_id=related_id,
                        related_type=template['related_type'],
                        created_at=datetime.now() - timedelta(days=random.randint(1, 7))
                    )
                    db.session.add(notification)
                    notifications_created += 1
            
            db.session.commit()
            print(f"✅ Created {notifications_created} notifications\n")
            
            # 9. Create Application Documents (checklist entries)
            print("📋 Creating application document checklists...")
            documents_created = 0
            
            # Create document checklist for each application
            applications = Applications.query.all()
            for application in applications:
                # Get program requirements
                prog_requirements = ProgramRequirements.query.filter_by(program_id=application.program_id).all()
                
                for prog_req in prog_requirements:
                    # Determine status based on application status and requirement type
                    if prog_req.requirement.requirement_type == 'document':
                        if application.application_status == 'approved':
                            submission_status = random.choice(['approved', 'approved', 'approved', 'pending'])
                        elif application.application_status == 'under_review':
                            submission_status = random.choice(['pending', 'on-hold', 'approved'])
                        else:
                            submission_status = 'pending'
                        
                        app_doc = ApplicationDocuments(
                            application_id=application.id,
                            requirement_id=prog_req.requirement_id,
                            submission_status=submission_status,
                            verified_by=admin_user.id if submission_status == 'approved' else None,
                            verified_at=datetime.now() - timedelta(days=random.randint(1, 5)) if submission_status == 'approved' else None
                        )
                    else:  # qualification type
                        qualification_met = random.choice([True, False]) if application.application_status != 'approved' else True
                        app_doc = ApplicationDocuments(
                            application_id=application.id,
                            requirement_id=prog_req.requirement_id,
                            qualification_met=qualification_met,
                            verified_by=admin_user.id if qualification_met else None,
                            verified_at=datetime.now() - timedelta(days=random.randint(1, 5)) if qualification_met else None
                        )
                    
                    db.session.add(app_doc)
                    documents_created += 1
            
            db.session.commit()
            print(f"✅ Created {documents_created} application document checklist entries\n")
            
            # 10. Create Program Workflow Steps for ESA programs
            print("⚙️ Creating program workflow steps...")
            workflow_steps_created = 0
            
            esa_programs = [p for p in programs if p.program_type == 'ESA']
            for program in esa_programs:
                # ESA workflow steps
                steps = [
                    {
                        'step_order': 1,
                        'step_name': 'Initial Document Verification',
                        'step_description': 'Verify submitted documents and barangay report',
                        'step_type': 'verification',
                        'is_pre_approval': True
                    },
                    {
                        'step_order': 2,
                        'step_name': 'Shelter Photo Upload',
                        'step_description': 'Upload photos of damaged shelter/property',
                        'step_type': 'photo_upload',
                        'is_pre_approval': True,
                        'min_items': 3,
                        'allowed_file_types': 'jpg,jpeg,png'
                    },
                    {
                        'step_order': 3,
                        'step_name': 'Site Inspection',
                        'step_description': 'On-site verification by MSWD staff',
                        'step_type': 'verification',
                        'is_pre_approval': True
                    },
                    {
                        'step_order': 4,
                        'step_name': 'Final Approval',
                        'step_description': 'Final approval and assistance scheduling',
                        'step_type': 'approval',
                        'is_pre_approval': False
                    }
                ]
                
                for step_data in steps:
                    workflow_step = ProgramWorkflowSteps(
                        program_id=program.id,
                        **step_data
                    )
                    db.session.add(workflow_step)
                    workflow_steps_created += 1
            
            db.session.commit()
            print(f"✅ Created {workflow_steps_created} workflow steps\n")
            
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
            print(f"✅ Announcements: {len(announcements)}")
            print(f"✅ Notifications: {notifications_created}")
            print(f"✅ Application Document Checklists: {documents_created}")
            print(f"✅ Program Workflow Steps: {workflow_steps_created}")
            print(f"✅ Barangays: {len(barangays)}")
            print("="*70)
            
            # Show statistics
            print("\n📈 APPLICATION STATISTICS:")
            status_counts = db.session.query(
                Applications.application_status,
                func.count(Applications.id)
            ).group_by(Applications.application_status).all()
            
            for status, count in status_counts:
                percentage = (count / applications_created * 100) if applications_created > 0 else 0
                print(f"   • {status.upper()}: {count} ({percentage:.1f}%)")
            
            print("\n📅 MONTHLY APPLICATION DISTRIBUTION:")
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_year = datetime.now().year
            for month in range(1, 13):
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
            pwd_count = CommunityUsers.query.filter_by(is_pwd=True).count()
            print(f"   • Employed: {employed_count}")
            print(f"   • Students: {student_count}")
            print(f"   • Solo Parents: {solo_parent_count}")
            print(f"   • PWD: {pwd_count}")
            
            avg_income = db.session.query(func.avg(CommunityUsers.family_annual_income)).scalar()
            print(f"   • Average Family Income: ₱{avg_income:,.2f}")
            
            print("\n📢 ANNOUNCEMENTS BREAKDOWN:")
            published_announcements = len([a for a in announcements if a.status == 'published'])
            draft_announcements = len(announcements) - published_announcements
            print(f"   • Published: {published_announcements}")
            print(f"   • Draft: {draft_announcements}")
            
            print("\n🔔 NOTIFICATIONS BREAKDOWN:")
            read_notifications = Notifications.query.filter_by(is_read=True).count()
            unread_notifications = notifications_created - read_notifications
            print(f"   • Read: {read_notifications}")
            print(f"   • Unread: {unread_notifications}")
            
            print("\n📋 DOCUMENT STATUS BREAKDOWN:")
            approved_docs = ApplicationDocuments.query.filter_by(submission_status='approved').count()
            pending_docs = ApplicationDocuments.query.filter_by(submission_status='pending').count()
            print(f"   • Approved Documents: {approved_docs}")
            print(f"   • Pending Documents: {pending_docs}")
            qualified_count = ApplicationDocuments.query.filter_by(qualification_met=True).count()
            print(f"   • Qualifications Met: {qualified_count}")
            
            print("\n⚙️ WORKFLOW STEPS BREAKDOWN:")
            if workflow_steps_created > 0:
                verification_steps = ProgramWorkflowSteps.query.filter_by(step_type='verification').count()
                photo_steps = ProgramWorkflowSteps.query.filter_by(step_type='photo_upload').count()
                approval_steps = ProgramWorkflowSteps.query.filter_by(step_type='approval').count()
                print(f"   • Verification Steps: {verification_steps}")
                print(f"   • Photo Upload Steps: {photo_steps}")
                print(f"   • Approval Steps: {approval_steps}")
            else:
                print("   • No workflow steps created")
            
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
            print("   Admin: MSWDMabitac@gmail.com / MabitacMSWD_2025")
            print("   Users: user1@test.com to user20@test.com / password123")
            
            return True
        
        except Exception as e:
            print(f"\n❌ Error during data population: {e}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            return False

if __name__ == '__main__':
    success = populate_dummy_data()
    if success:
        print("SUCCESS: Script completed successfully!")
    else:
        print("ERROR: Script failed. Please check the errors above.")
        exit(1)