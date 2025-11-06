from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import User
from werkzeug.security import generate_password_hash, check_password_hash
from .. import db
from flask_login import login_user, login_required, logout_user, current_user

auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
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

        # Log successful login (Add Audit Log)
        
        # if user is an admin, create admin log

        # Redirect based on role (admin/user) or default home
        def _post_login_redirect(user):
            if user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            if user.role == 'community':
                return redirect(url_for('community.dashboard'))
            return redirect(url_for('views.home'))
        
        return _post_login_redirect(user)

    return render_template("auth/login.html", user=current_user)

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))

@auth.route('/about')
def about():
    return render_template("about.html", user=current_user)

@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        email = request.form.get('email')  
        firstName = request.form.get('firstName')
        lastName = request.form.get('lastName') 
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')

        user = User.query.filter_by(email=email).first()

        if user: 
            flash('Email already exists.', category='error')
        elif len(email) < 4: 
            flash('Email must be greater than 3 characters.', category='error')
        elif len(firstName) < 2:
            flash('First name must be greater than 1 character.', category='error')
        elif len(lastName) < 2:
            flash('Last name must be greater than 1 character.', category='error')
        elif password1 != password2:
            flash('Passwords don\'t match.', category='error')
        elif len(password1) < 7:
            flash('Password must be at least 7 characters.', category='error')
        else:  
            new_user = User(email=email, first_name=firstName, last_name=lastName, role='community', password_hash=generate_password_hash(
                password1, method='pbkdf2:sha256'))
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user, remember=True)
            flash('Account created!', category='success')
            return redirect(url_for('views.home'))
    
    return render_template("auth/sign_up.html", user=current_user)
