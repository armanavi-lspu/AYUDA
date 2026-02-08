"""
Script to populate the database with community user profiles and applications
Run this with: flask populate-dummy-data
Note: Run migrations first: flask db upgrade, then flask init-db for basic data

This script creates:
- Community users with realistic demographic data  
- Time series applications data for ARIMA forecasting (18 months)
- Does NOT create: programs, requirements, announcements, notifications, or workflow steps
"""

from app import create_app, db
from app.models import (
    User, Programs, Applications, CommunityUsers, AdminUsers, Requirements, 
    ProgramRequirements, ShelterPhotos, ProgramWorkflowSteps, 
    ApplicationDocuments, ApplicationDocumentUploads, CALDocuments,
    Announcements, Notifications
)
from datetime import datetime, timedelta
import random
import numpy as np
from werkzeug.security import generate_password_hash
from sqlalchemy import func

def populate_dummy_data():
    """Populate database with community user profiles and applications"""
    
    app = create_app()
    
    with app.app_context():
        try:
            print("Starting to populate community users and applications...\n")
            
            # Clear existing user data only (keep programs, requirements, admin)
            print("⚠️  Clearing existing community users and applications...")
            try:
                # Clear in proper order to respect foreign key constraints
                CALDocuments.query.delete()
                ApplicationDocumentUploads.query.delete()
                ApplicationDocuments.query.delete()
                ShelterPhotos.query.delete()
                Notifications.query.filter(
                    Notifications.user_id.in_(
                        db.session.query(User.id).filter_by(role='community')
                    )
                ).delete(synchronize_session='fetch')
                Applications.query.filter(
                    Applications.user_id.in_(
                        db.session.query(User.id).filter_by(role='community')
                    )
                ).delete(synchronize_session='fetch')
                CommunityUsers.query.delete()
                # Only delete community users, not admins or programs
                User.query.filter_by(role='community').delete()
                db.session.commit()
                print("✅ Existing community data cleared\n")
            except Exception as e:
                print(f"⚠️  Warning: Could not clear all existing data: {e}")
                db.session.rollback()
                print("   Continuing with population...\n")
            
            # Get existing admin user and programs from database
            admin_user = User.query.filter_by(role='admin').first()
            if not admin_user:
                print("❌ No admin user found! Please run the SQL file first.")
                return False
            
            programs = Programs.query.all()
            if not programs:
                print("❌ No programs found! Please run the SQL file first.")
                return False
            
            print(f"✅ Found {len(programs)} existing programs\n")
            
            # 1. Create Community Users
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
                
                # Generate unique email (start from user21 to avoid conflicts with sample user)
                email = f'user{i+21}@test.com'
                
                # Check if user already exists, skip if so
                existing_user = User.query.filter_by(email=email).first()
                if existing_user:
                    print(f"   ⚠️  User {email} already exists, skipping...")
                    continue
                
                user = User(
                    email=email,
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
            
            # 2. Create Applications with time series data for ARIMA forecasting
            # Generate 18 months of data (Jan 2024 - Jun 2025) to ensure ARIMA works
            # ARIMA requires at least 12 continuous months of data
            print("📝 Creating applications with time series data for ARIMA...")

            applications_created = 0

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
                    status_choices = ['pending', 'approved', 'rejected', 'active', 'completed']
                    status_weights = [0.30, 0.25, 0.10, 0.20, 0.15]
                    application_status = np.random.choice(status_choices, p=status_weights)

                    # Create application with new fields
                    document_upload_status = 'pending'
                    claim_status = 'not_scheduled'
                
                    # Set document upload status based on application status
                    if application_status == 'active':
                        document_upload_status = random.choice(['uploaded', 'verified', 'pending'])
                    elif application_status == 'approved':
                        document_upload_status = 'pending'
                    elif application_status == 'completed':
                        document_upload_status = 'verified'
                        if random.random() < 0.5:  # 50% chance to have claim scheduled
                            claim_status = random.choice(['scheduled', 'claimed', 'missed'])
                    
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
                
                # Add verification code for some active/approved applications
                if application_status in ['approved', 'active'] and random.random() < 0.5:
                    application.generate_verification_code()
                
                db.session.add(application)
                applications_created += 1

            db.session.commit()
            print(f"✅ Created {applications_created} applications\n")
            
            # Print summary
            print("="*70)  
            print("📊 DATA SUMMARY")
            print("="*70)
            print(f"✅ Community Users: {len(community_users)}")
            print(f"✅ Programs: {len(programs)} (loaded from database)")
            print(f"✅ Applications: {applications_created}")
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
            
            print("\n� ASSISTANCE CLAIM STATUS:")
            claim_statuses = ['not_scheduled', 'scheduled', 'claimed', 'missed']
            for status in claim_statuses:
                count = Applications.query.filter_by(claim_status=status).count()
                percentage = (count / applications_created * 100) if applications_created > 0 else 0
                print(f"   • {status.replace('_', ' ').upper()}: {count} ({percentage:.1f}%)")
            
            print(f"\n📋 PROGRAMS LOADED FROM DATABASE: {len(programs)}")
            
            print("\n" + "="*70)
            print("🎉 Community users and applications population completed successfully!")
            print("="*70)
            print("\n📝 Login credentials:")
            print("   Admin: MSWDMabitac@gmail.com / MabitacMSWD_2025")
            print("   Sample User: user1@test.com / password123 (created via flask init-db)")
            print("   Test Users: user21@test.com to user40@test.com / password123")
            print("\n💡 Note: Run 'flask db upgrade' then 'flask init-db' first to set up database structure and basic data.")
            
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