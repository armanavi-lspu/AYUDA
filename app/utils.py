from functools import wraps
from flask import redirect, url_for, flash, current_app
from flask_login import current_user
import datetime
import pytz


def _parse_priority_group_tokens(priority_group):
    """Split a program priority_group string into normalized tokens."""
    if not priority_group:
        return []
    return [token.strip().lower() for token in str(priority_group).split(',') if token.strip()]


def evaluate_program_profile_eligibility(priority_group, community_profile):
    """
    Evaluate whether a community profile is eligible based on program priority groups.

    Rules:
    - If no profile-based priority group is configured, everyone is eligible.
    - If one or more profile-based groups are configured, user must match at least one.
    """
    tokens = _parse_priority_group_tokens(priority_group)

    # Only these groups are enforceable using profile fields we already store.
    enforceable_checks = {
        'students': lambda p: bool(p and p.is_student),
        'student': lambda p: bool(p and p.is_student),
        'senior citizens': lambda p: bool(p and (p.age or 0) >= 60),
        'senior citizen': lambda p: bool(p and (p.age or 0) >= 60),
        'seniors': lambda p: bool(p and (p.age or 0) >= 60),
        'single parents': lambda p: bool(p and p.is_solo_parent),
        'single parent': lambda p: bool(p and p.is_solo_parent),
        'solo parent': lambda p: bool(p and p.is_solo_parent),
        'pwds (persons with disabilities)': lambda p: bool(p and p.is_pwd),
        'pwd': lambda p: bool(p and p.is_pwd),
        'persons with disabilities': lambda p: bool(p and p.is_pwd),
        'low income families': lambda p: bool(p and p.family_annual_income is not None and float(p.family_annual_income) <= 250000),
        'indigent families': lambda p: bool(p and p.family_annual_income is not None and float(p.family_annual_income) <= 250000),
        'not employed individuals': lambda p: bool(p and not p.is_currently_employed),
    }

    enforceable_tokens = [token for token in tokens if token in enforceable_checks]
    if not enforceable_tokens:
        return {
            'is_eligible': True,
            'required_groups': [],
            'matched_groups': [],
        }

    matched_groups = [
        token for token in enforceable_tokens
        if enforceable_checks[token](community_profile)
    ]

    return {
        'is_eligible': len(matched_groups) > 0,
        'required_groups': enforceable_tokens,
        'matched_groups': matched_groups,
    }

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
    """Format datetime for display in local timezone"""
    if not timestamp:
        return "N/A"
    if isinstance(timestamp, str):
        return timestamp
    
    try:
        # Get the configured timezone
        tz = current_app.config.get('TZ', pytz.timezone('Asia/Manila'))
        
        # Convert UTC timestamp to local timezone
        # If timestamp is naive (no timezone info), assume it's UTC
        if timestamp.tzinfo is None:
            timestamp_utc = pytz.utc.localize(timestamp)
        else:
            timestamp_utc = timestamp
        
        timestamp_local = timestamp_utc.astimezone(tz)
        
        # Get current time in local timezone
        now_local = datetime.datetime.now(tz)
        
        # Calculate difference using local times
        diff = now_local - timestamp_local
        
        if diff.days == 0:
            return timestamp_local.strftime('%I:%M %p')
        elif diff.days < 7:
            return timestamp_local.strftime('%a, %I:%M %p')
        else:
            return timestamp_local.strftime('%b %d, %Y %I:%M %p')
    except Exception as e:
        # Fallback if timezone conversion fails
        print(f"Timezone conversion error: {e}")
        return str(timestamp) 


def calculate_profile_completion(user):
    """
    Calculate the profile completion percentage for a community user.
    
    Args:
        user: User object (must have community_profile relationship)
        
    Returns:
        dict: {
            'percentage': int (0-100),
            'is_complete': bool,
            'missing_fields': list of str,
            'completed_fields': list of str
        }
    """
    if not user or user.role != 'community':
        return {
            'percentage': 0,
            'is_complete': False,
            'missing_fields': [],
            'completed_fields': []
        }
    
    profile = user.community_profile
    
    # Define required fields for profile completion
    required_fields = {
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'age': profile.age if profile else None,
        'gender': profile.gender if profile else None,
        'mobile_no': profile.mobile_no if profile else None,
        'birth_year': profile.birth_year if profile else None,
        'barangay': profile.barangay if profile else None,
        'address': profile.address if profile else None,
        'municipality': profile.municipality if profile else None,
        'occupation': profile.occupation if profile else None,
        'family_annual_income': profile.family_annual_income if profile else None,
    }
    
    # Optional but important fields (not required but add to percentage)
    optional_fields = {
        'birth_month': profile.birth_month if profile else None,
        'birth_day': profile.birth_day if profile else None,
        'sitio': profile.sitio if profile else None,
        'is_currently_employed': profile.is_currently_employed if profile else None,
        'is_student': profile.is_student if profile else None,
    }
    
    # Check required fields
    completed_required = []
    missing_required = []
    
    for field_name, field_value in required_fields.items():
        if field_value is not None and str(field_value).strip():
            completed_required.append(field_name)
        else:
            missing_required.append(field_name)
    
    # Check optional fields
    completed_optional = []
    
    for field_name, field_value in optional_fields.items():
        if field_value is not None and str(field_value).strip():
            completed_optional.append(field_name)
    
    # Calculate percentage (Required = 80%, Optional = 20%)
    required_percentage = (len(completed_required) / len(required_fields)) * 80
    optional_percentage = (len(completed_optional) / len(optional_fields)) * 20
    total_percentage = int(required_percentage + optional_percentage)
    
    # Profile is complete if all required fields are filled
    is_complete = len(missing_required) == 0
    
    # User-friendly field names
    field_labels = {
        'first_name': 'First Name', 'last_name': 'Last Name', 'email': 'Email Address',
        'age': 'Age', 'gender': 'Gender', 'mobile_no': 'Mobile Number',
        'birth_year': 'Birth Year', 'birth_month': 'Birth Month', 'birth_day': 'Birth Day',
        'barangay': 'Barangay', 'sitio': 'Sitio', 'address': 'Complete Address',
        'municipality': 'Municipality', 'occupation': 'Occupation',
        'family_annual_income': 'Family Annual Income',
        'is_currently_employed': 'Employment Status', 'is_student': 'Student Status'
    }
    
    return {
        'percentage': total_percentage,
        'is_complete': is_complete,
        'missing_fields': [field_labels.get(f, f) for f in missing_required],
        'completed_fields': [field_labels.get(f, f) for f in completed_required],
        'missing_count': len(missing_required),
        'required_total': len(required_fields)
    }
