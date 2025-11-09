from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user
import datetime

def redirect_user_by_role(user):
    """Redirect user to appropriate dashboard based on their role."""
    if user.role == 'admin':
        return redirect(url_for('admin.dashboard'))
    if user.role == 'community':
        return redirect(url_for('community.dashboard'))
    return redirect(url_for('views.home'))

def role_required(allowed_role):
    """
    Single decorator for role-based access control.
    :param allowed_role: 'admin'
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Debug information
            print(f"Current user authenticated: {current_user.is_authenticated}")
            if current_user.is_authenticated:
                print(f"Current user role: {current_user.role}")
                print(f"Required roles: {allowed_role}")
                
            if not current_user.is_authenticated:
                flash('Please login to access this page.', 'warning')
                return redirect(url_for('auth.login'))
            
            if current_user.role not in allowed_role:
                flash(f'Access denied. This page is for {allowed_role} users only.', 'danger')
                return redirect_user_by_role(current_user)
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def format_date(timestamp):
    """Format datetime for display"""
    if not timestamp:
        return "N/A"
    if isinstance(timestamp, str):
        return timestamp
        
    now = datetime.datetime.utcnow()
    diff = now - timestamp
    
    if diff.days == 0:
        return timestamp.strftime('%I:%M %p')
    elif diff.days < 7:
        return timestamp.strftime('%a, %I:%M %p')
    else:
        return timestamp.strftime('%b %d, %Y %I:%M %p')