from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import User, CommunityUsers
from werkzeug.security import generate_password_hash, check_password_hash
from .. import db
from flask_login import login_user, login_required, logout_user, current_user
from ..utils import redirect_user_by_role
from datetime import datetime

auth_bp = Blueprint('auth', __name__, template_folder='../templates')

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

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/about')
def about():
    return render_template("about.html", user=current_user)

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
        age = request.form.get('age')
        birth_month = request.form.get('birth_month')
        birth_day = request.form.get('birth_day')
        birth_year = request.form.get('birth_year')
        mobile_no = request.form.get('mobile_no')
        
        # Address Information
        barangay = request.form.get('barangay')
        sitio = request.form.get('sitio')
        municipality = request.form.get('municipality', 'Mabitac')
        
        # Household & Employment Information
        family_annual_income = request.form.get('family_annual_income')
        is_currently_employed = request.form.get('is_currently_employed') == 'on'
        is_student = request.form.get('is_student') == 'on'
        is_solo_parent = request.form.get('is_solo_parent') == 'on'
        
        # Terms
        terms = request.form.get('terms')

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
        elif not age or int(age) < 1:
            flash('Please enter a valid age.', category='error')
        elif not birth_month or not birth_day or not birth_year:
            flash('Please enter your complete birth date.', category='error')
        elif not barangay:
            flash('Please select your barangay.', category='error')
        elif password1 != password2:
            flash('Passwords don\'t match.', category='error')
        elif len(password1) < 7:
            flash('Password must be at least 7 characters.', category='error')
        elif not terms:
            flash('You must accept the Terms and Conditions.', category='error')
        else:
            try:
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
                    age=int(age),
                    mobile_no=mobile_no if mobile_no else None,
                    birth_month=int(birth_month),
                    birth_day=int(birth_day),
                    birth_year=int(birth_year),
                    barangay=barangay,
                    sitio=sitio if sitio else None,
                    municipality=municipality,
                    is_currently_employed=is_currently_employed,
                    is_student=is_student,
                    is_solo_parent=is_solo_parent,
                    family_annual_income=float(family_annual_income) if family_annual_income else None
                )
                db.session.add(community_profile)
                db.session.commit()
                
                login_user(new_user, remember=True)
                flash('Account created successfully! Welcome to AYUDA!', category='success')
                return redirect(url_for('community.dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred while creating your account: {str(e)}', category='error')
    
    return render_template("auth/sign_up.html", user=current_user)
