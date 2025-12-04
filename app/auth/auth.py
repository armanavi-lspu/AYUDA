from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import User, CommunityUsers
from werkzeug.security import generate_password_hash, check_password_hash
from .. import db
from flask_login import login_user, login_required, logout_user, current_user
from ..utils import redirect_user_by_role
from datetime import datetime, date

auth_bp = Blueprint('auth', __name__, template_folder='../templates')


@auth_bp.route('/about')
def about():
    return render_template("about.html", user=current_user)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if not user:
            flash('Email does not exist.', category='error')
            return render_template("auth/login.html", user=current_user)
        if not check_password_hash(user.password_hash, password):
            flash('Incorrect password, try again.', category='error')
            return render_template("auth/login.html", user=current_user)

        # Successful login
        login_user(user, remember=True)
        flash('Logged in successfully!', category='success')

        # Use utility function for role-based redirect
        return redirect_user_by_role(user)

    return render_template("auth/login.html", user=current_user)

@auth_bp.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        # Account Information
        email = request.form.get('email')
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')
        
        # Personal Information
        firstName = request.form.get('firstName')
        middleName = request.form.get('middleName')
        lastName = request.form.get('lastName')
        birthDate = request.form.get('birthDate')  # YYYY-MM-DD format
        mobileNo = request.form.get('mobileNo')
        
        # Address Information
        barangay = request.form.get('barangay')
        sitio = request.form.get('sitio', '').strip()  # Optional
        address = request.form.get('address')
        municipality = 'Mabitac'  # Fixed value
        
        # Additional Details
        familyIncome = request.form.get('familyIncome')
        isEmployed = request.form.get('isEmployed') == 'on'
        occupation = request.form.get('occupation', '').strip() if isEmployed else None
        isStudent = request.form.get('isStudent') == 'on'
        isSoloParent = request.form.get('isSoloParent') == 'on'
        isPWD = request.form.get('isPWD') == 'on'
        disabilityType = request.form.get('disabilityType', '').strip() if isPWD else None
        
        # Terms
        agreeTerms = request.form.get('agreeTerms')

        # Validation
        user = User.query.filter_by(email=email).first()

        if user:
            flash('Email already exists.', category='error')
        elif len(email) < 4:
            flash('Email must be greater than 3 characters.', category='error')
        elif len(firstName) < 2:
            flash('First name must be greater than 1 character.', category='error')
        elif len(lastName) < 2:
            flash('Last name must be greater than 1 character.', category='error')
        elif not birthDate:
            flash('Please enter your birth date.', category='error')
        elif not barangay:
            flash('Please select your barangay.', category='error')
        elif not address or len(address) < 10:
            flash('Please provide a complete address (at least 10 characters).', category='error')
        elif isEmployed and not occupation:
            flash('Please enter your occupation since you selected "Currently Employed".', category='error')
        elif isPWD and not disabilityType:
            flash('Please enter your specific disability since you selected "PWD".', category='error')
        elif password1 != password2:
            flash('Passwords don\'t match.', category='error')
        elif len(password1) < 7:
            flash('Password must be at least 7 characters.', category='error')
        elif not agreeTerms:
            flash('You must accept the Terms and Conditions.', category='error')
        else:
            try:
                # Parse birth date and calculate age
                birth_date_obj = datetime.strptime(birthDate, '%Y-%m-%d').date()
                today = date.today()
                age = today.year - birth_date_obj.year - ((today.month, today.day) < (birth_date_obj.month, birth_date_obj.day))
                
                # Check if user is at least 18 years old
                if age < 18:
                    flash('You must be at least 18 years old to register.', category='error')
                    return render_template("auth/sign_up.html", user=current_user)
                
                # Create User account
                new_user = User(
                    email=email,
                    first_name=firstName,
                    middle_name=middleName if middleName else None,
                    last_name=lastName,
                    role='community',
                    password_hash=generate_password_hash(password1, method='pbkdf2:sha256')
                )
                db.session.add(new_user)
                db.session.flush()  # Get the user ID
                
                # Create CommunityUsers profile
                community_profile = CommunityUsers(
                    user_id=new_user.id,
                    age=age,
                    mobile_no=mobileNo if mobileNo else None,
                    birth_month=birth_date_obj.month,
                    birth_day=birth_date_obj.day,
                    birth_year=birth_date_obj.year,
                    barangay=barangay,
                    sitio=sitio if sitio else None,
                    address=address,
                    municipality=municipality,
                    is_currently_employed=isEmployed,
                    occupation=occupation,
                    is_student=isStudent,
                    is_solo_parent=isSoloParent,
                    is_pwd=isPWD,
                    disability_type=disabilityType,
                    family_annual_income=float(familyIncome) if familyIncome else None
                )
                db.session.add(community_profile)
                db.session.commit()
                
                login_user(new_user, remember=True)
                flash('Account created successfully! Welcome to AYUDA!', category='success')
                return redirect(url_for('community.dashboard'))
                
            except ValueError as ve:
                db.session.rollback()
                flash(f'Invalid date format: {str(ve)}', category='error')
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred while creating your account: {str(e)}', category='error')
    
    return render_template("auth/sign_up.html", user=current_user)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))