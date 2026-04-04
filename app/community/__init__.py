from flask import Blueprint, redirect, url_for, flash, session
from flask_login import current_user

community_bp = Blueprint('community', __name__, url_prefix='/community')

# Import routes after blueprint creation to avoid circular imports
from .routes import dashboard, announcements, applications, programs, notifications, schedule, profile, other_services

# Routes that don't require areas of concern check
AREAS_CHECK_EXEMPT = {
    'community.areas_of_concern',
    'community.skip_areas_of_concern',
    'community.profile',
    'community.edit_profile',
    'community.settings',
    'community.change_password',
    'community.update_notification_settings',
    'community.update_privacy_settings',
    'community.export_user_data',
    'community.delete_account',
    'community.activity_logs',
    'community.api.profile_completion',
    'community.profile.verify',
    'community.verification_status'
}

@community_bp.before_request
def check_areas_of_concern():
    """Check if user has selected 2 areas of concern before accessing sidebar content"""
    from flask import request
    from app.models import CommunityUsers
    
    # Skip check for non-authenticated users or admins
    if not current_user.is_authenticated or current_user.role != 'community':
        return
    
    # Skip check for exempt routes
    if request.endpoint in AREAS_CHECK_EXEMPT:
        return
    
    # Skip check for areas_of_concern related routes
    if 'areas_of_concern' in request.path:
        return
    
    # Check if user has selected 2 areas
    community_profile = CommunityUsers.query.filter_by(user_id=current_user.id).first()
    if community_profile:
        areas = community_profile.get_areas_of_concern()
        if len(areas) == 2:
            session.pop('skip_areas_of_concern', None)
            return

        if session.get('skip_areas_of_concern'):
            return

        if len(areas) != 2:
            flash('Please select your 2 areas of concern to continue.', 'info')
            return redirect(url_for('community.areas_of_concern', next=request.url))  