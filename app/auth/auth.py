from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from ..models import User, CommunityUsers
from werkzeug.security import generate_password_hash, check_password_hash
from .. import db
from flask_login import login_user, login_required, logout_user, current_user
from ..utils import redirect_user_by_role
from ..user_activity_logger import log_login, log_logout
from datetime import datetime, date

auth_bp = Blueprint('auth', __name__, template_folder='../templates')


@auth_bp.route('/about')
def about():
    return render_template("about.html", user=current_user)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    def is_ajax_request():
        return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''

        # Server-side validation for both regular and AJAX requests
        if not email:
            if is_ajax_request():
                return jsonify({'success': False, 'message': 'Email is required.', 'field': 'email'}), 400
            flash('Email is required.', category='error')
            return render_template("auth/login.html", user=current_user)

        if not password:
            if is_ajax_request():
                return jsonify({'success': False, 'message': 'Password is required.', 'field': 'password'}), 400
            flash('Password is required.', category='error')
            return render_template("auth/login.html", user=current_user)

        user = User.query.filter_by(email=email).first()

        if not user:
            if is_ajax_request():
                return jsonify({'success': False, 'message': 'Email does not exist.', 'field': 'email'}), 401
            flash('Email does not exist.', category='error')
            return render_template("auth/login.html", user=current_user)

        if not check_password_hash(user.password_hash, password):
            if is_ajax_request():
                return jsonify({'success': False, 'message': 'Incorrect password. Please try again.', 'field': 'password'}), 401
            flash('Incorrect password, try again.', category='error')
            return render_template("auth/login.html", user=current_user)

        # Successful login
        login_user(user, remember=True)
        
        # Log login activity (only for community users)
        if user.role == 'community':
            log_login(user.id)
            db.session.commit()

        if is_ajax_request():
            if user.role == 'admin':
                redirect_url = url_for('admin.dashboard')
            elif user.role == 'community':
                redirect_url = url_for('community.dashboard')
            else:
                redirect_url = url_for('views.home')
            return jsonify({'success': True, 'redirect_url': redirect_url}), 200
        
        flash('Logged in successfully!', category='success')

        # Use utility function for role-based redirect
        return redirect_user_by_role(user)

    return render_template("auth/login.html", user=current_user)

@auth_bp.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        # Account Information
        email = request.form.get('email')
        password = request.form.get('password')
        confirmPassword = request.form.get('confirmPassword')
        
        # Personal Information
        firstName = request.form.get('firstName')
        lastName = request.form.get('lastName')
        birthDate = request.form.get('birthDate')  # YYYY-MM-DD format
        gender = request.form.get('gender')

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
        elif not gender:
            flash('Please select your gender.', category='error')
        elif password != confirmPassword:
            flash('Passwords don\'t match.', category='error')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', category='error')
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
                    last_name=lastName,
                    role='community',
                    password_hash=generate_password_hash(password, method='pbkdf2:sha256')
                )
                db.session.add(new_user)
                db.session.flush()  # Get the user ID
                
                # Create CommunityUsers profile with basic information
                community_profile = CommunityUsers(
                    user_id=new_user.id,
                    age=age,
                    birth_month=birth_date_obj.month,
                    birth_day=birth_date_obj.day,
                    birth_year=birth_date_obj.year,
                    gender=gender
                )
                db.session.add(community_profile)
                db.session.commit()
                
                login_user(new_user, remember=True)
                flash('Account created successfully! Please select your areas of concern to get personalized recommendations.', category='success')
                return redirect(url_for('community.areas_of_concern', next=url_for('community.dashboard')))
                
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
    # Log logout activity (only for community users)
    if current_user.role == 'community':
        log_logout()
        db.session.commit()
    
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))