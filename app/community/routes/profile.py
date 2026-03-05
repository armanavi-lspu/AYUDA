"""
Community user profile and settings management routes.
Handles viewing and updating user profile information and system preferences.
"""

from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.community import community_bp
from app.extensions import db
from app.models import User, CommunityUsers, Notifications, UserActivityLog
from app.utils import calculate_profile_completion
from app.user_activity_logger import log_profile_edit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from sqlalchemy import desc


@community_bp.route('/profile')
@login_required
def profile():
    """Display user profile page with personal information."""
    if current_user.role != 'community':
        flash('Access denied. This page is for community users only.', 'error')
        return redirect(url_for('home.index'))
    
    community_profile = CommunityUsers.query.filter_by(user_id=current_user.id).first()
    completion_data = calculate_profile_completion(current_user)
    
    return render_template('community/profile.html', 
                         user=current_user,
                         profile=community_profile,
                         completion=completion_data)


@community_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit user profile information."""
    if current_user.role != 'community':
        flash('Access denied. This page is for community users only.', 'error')
        return redirect(url_for('home.index'))
    
    community_profile = CommunityUsers.query.filter_by(user_id=current_user.id).first()
    
    if request.method == 'POST':
        try:
            # Update User table fields
            current_user.first_name = request.form.get('first_name', '').strip()
            current_user.middle_name = request.form.get('middle_name', '').strip()
            current_user.last_name = request.form.get('last_name', '').strip()
            
            # Update CommunityUsers table fields
            if community_profile:
                community_profile.mobile_no = request.form.get('mobile_no', '').strip()
                community_profile.birth_month = request.form.get('birth_month')
                community_profile.birth_day = request.form.get('birth_day')
                community_profile.birth_year = request.form.get('birth_year')
                community_profile.gender = request.form.get('gender')
                community_profile.barangay = request.form.get('barangay', '').strip()
                community_profile.sitio = request.form.get('sitio', '').strip()
                community_profile.municipality = request.form.get('municipality', 'Mabitac').strip()
                community_profile.address = request.form.get('address', '').strip()
                community_profile.occupation = request.form.get('occupation', '').strip()
                community_profile.is_currently_employed = request.form.get('is_currently_employed') == 'on'
                community_profile.is_student = request.form.get('is_student') == 'on'
                community_profile.is_solo_parent = request.form.get('is_solo_parent') == 'on'
                community_profile.is_pwd = request.form.get('is_pwd') == 'on'
                community_profile.disability_type = request.form.get('disability_type', '').strip() if community_profile.is_pwd else None
                
                # Parse family annual income with validation
                income_str = request.form.get('family_annual_income', '').strip()
                if income_str:
                    try:
                        # Remove commas and convert to float
                        income_value = float(income_str.replace(',', ''))
                        
                        # Validate income range
                        if income_value < 0:
                            flash('Family annual income cannot be negative.', 'error')
                            return redirect(url_for('community.edit_profile'))
                        elif income_value > 10000000:  # 10 million max
                            flash('Family annual income exceeds maximum allowed value (₱10,000,000).', 'error')
                            return redirect(url_for('community.edit_profile'))
                        
                        community_profile.family_annual_income = income_value
                    except ValueError:
                        flash('Invalid income format. Please enter a valid number.', 'error')
                        return redirect(url_for('community.edit_profile'))
                
                # Calculate age from birth date
                if community_profile.birth_year:
                    current_year = datetime.now().year
                    community_profile.age = current_year - int(community_profile.birth_year)
            
            # Log profile edit
            log_profile_edit()
            
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('community.profile'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {str(e)}', 'error')
    
    return render_template('community/edit_profile.html', 
                         user=current_user,
                         profile=community_profile)


@community_bp.route('/settings')
@login_required
def settings():
    """Display user settings page."""
    if current_user.role != 'community':
        flash('Access denied. This page is for community users only.', 'error')
        return redirect(url_for('home.index'))
    
    return render_template('community/settings.html', user=current_user)


@community_bp.route('/settings/change-password', methods=['POST'])
@login_required
def change_password():
    """Change user password."""
    if current_user.role != 'community':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    # Validate inputs
    if not all([current_password, new_password, confirm_password]):
        flash('All password fields are required.', 'error')
        return redirect(url_for('community.settings'))
    
    if not check_password_hash(current_user.password_hash, current_password):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('community.settings'))
    
    if new_password != confirm_password:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('community.settings'))
    
    if len(new_password) < 8:
        flash('Password must be at least 8 characters long.', 'error')
        return redirect(url_for('community.settings'))
    
    try:
        current_user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
        db.session.commit()
        flash('Password changed successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error changing password: {str(e)}', 'error')
    
    return redirect(url_for('community.settings'))


@community_bp.route('/settings/notifications', methods=['POST'])
@login_required
def update_notification_settings():
    """Update notification preferences."""
    if current_user.role != 'community':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    # For now, we'll just acknowledge the settings
    # In a full implementation, you'd store these preferences in the database
    flash('Notification settings updated successfully!', 'success')
    return redirect(url_for('community.settings'))


@community_bp.route('/settings/delete-account', methods=['POST'])
@login_required
def delete_account():
    """Delete user account (soft delete or hard delete)."""
    if current_user.role != 'community':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    password = request.form.get('confirm_password')
    
    if not check_password_hash(current_user.password_hash, password):
        flash('Password is incorrect. Account deletion cancelled.', 'error')
        return redirect(url_for('community.settings'))
    
    try:
        # Get user ID before deletion
        user_id = current_user.id
        
        # Delete community profile first (cascade should handle this, but being explicit)
        community_profile = CommunityUsers.query.filter_by(user_id=user_id).first()
        if community_profile:
            db.session.delete(community_profile)
        
        # Delete the user account
        user = User.query.get(user_id)
        db.session.delete(user)
        db.session.commit()
        
        flash('Your account has been successfully deleted.', 'info')
        return redirect(url_for('auth.logout'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting account: {str(e)}', 'error')
        return redirect(url_for('community.settings'))


@community_bp.route('/api/profile-completion')
@login_required
def api_profile_completion():
    """API endpoint to get profile completion status."""
    if current_user.role != 'community':
        return jsonify({'error': 'Access denied'}), 403
    
    completion_data = calculate_profile_completion(current_user)
    return jsonify(completion_data)


# ============== VERIFICATION REQUEST ROUTES ==============

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'verification_documents')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@community_bp.route('/profile/verify/<verification_type>', methods=['POST'])
@login_required
def request_verification(verification_type):
    """Submit a verification request for Senior Citizen, PWD, or Solo Parent status."""
    if current_user.role != 'community':
        flash('Access denied. This page is for community users only.', 'error')
        return redirect(url_for('home.index'))
    
    community_profile = CommunityUsers.query.filter_by(user_id=current_user.id).first()
    
    if not community_profile:
        flash('Please complete your profile first.', 'error')
        return redirect(url_for('community.edit_profile'))
    
    # Validate verification type
    valid_types = ['senior_citizen', 'pwd', 'solo_parent']
    if verification_type not in valid_types:
        flash('Invalid verification type.', 'error')
        return redirect(url_for('community.profile'))
    
    # Check if user has indicated they are in this category
    if verification_type == 'senior_citizen':
        if community_profile.age is None or community_profile.age < 60:
            flash('Senior Citizen verification requires you to be 60 years old or above.', 'error')
            return redirect(url_for('community.profile'))
        current_status = community_profile.senior_citizen_verification
    elif verification_type == 'pwd':
        if not community_profile.is_pwd:
            flash('Please indicate that you are a PWD in your profile first.', 'error')
            return redirect(url_for('community.edit_profile'))
        current_status = community_profile.pwd_verification
    elif verification_type == 'solo_parent':
        if not community_profile.is_solo_parent:
            flash('Please indicate that you are a Solo Parent in your profile first.', 'error')
            return redirect(url_for('community.edit_profile'))
        current_status = community_profile.solo_parent_verification
    
    # Check if already pending or approved
    if current_status == 'pending':
        flash('You already have a pending verification request. Please wait for admin review.', 'info')
        return redirect(url_for('community.profile'))
    elif current_status == 'approved':
        flash('Your verification has already been approved.', 'info')
        return redirect(url_for('community.profile'))
    
    # Check for uploaded file
    if 'id_document' not in request.files:
        flash('Please upload your ID document.', 'error')
        return redirect(url_for('community.profile'))
    
    file = request.files['id_document']
    
    if file.filename == '':
        flash('No file selected. Please upload your ID document.', 'error')
        return redirect(url_for('community.profile'))
    
    if not allowed_file(file.filename):
        flash('Invalid file type. Please upload a PNG, JPG, JPEG, or PDF file.', 'error')
        return redirect(url_for('community.profile'))
    
    try:
        # Create upload directory if it doesn't exist
        upload_path = os.path.join(os.getcwd(), UPLOAD_FOLDER)
        os.makedirs(upload_path, exist_ok=True)
        
        # Generate unique filename
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{current_user.id}_{verification_type}_{timestamp}_{filename}"
        file_path = os.path.join(upload_path, unique_filename)
        
        # Save the file
        file.save(file_path)
        
        # Update verification status and document path
        relative_path = f'/{UPLOAD_FOLDER}/{unique_filename}'
        id_number = request.form.get('id_number', '').strip()
        
        if verification_type == 'senior_citizen':
            community_profile.senior_citizen_verification = 'pending'
            community_profile.senior_citizen_document_path = relative_path
            if id_number:
                community_profile.senior_citizen_id_number = id_number
            verification_name = 'Senior Citizen'
        elif verification_type == 'pwd':
            community_profile.pwd_verification = 'pending'
            community_profile.pwd_document_path = relative_path
            if id_number:
                community_profile.pwd_id_number = id_number
            verification_name = 'PWD (Person with Disability)'
        elif verification_type == 'solo_parent':
            community_profile.solo_parent_verification = 'pending'
            community_profile.solo_parent_document_path = relative_path
            if id_number:
                community_profile.solo_parent_id_number = id_number
            verification_name = 'Solo Parent'
        
        # Create notification for the user
        notification = Notifications(
            user_id=current_user.id,
            notif_title=f'{verification_name} Verification Submitted',
            notif_message=f'Your {verification_name} verification request has been submitted. Please wait for admin review.',
            is_read=False,
            related_type='profile',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        
        db.session.commit()
        flash(f'Your {verification_name} verification request has been submitted successfully! Please wait for admin review.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error submitting verification request: {str(e)}', 'error')
    
    return redirect(url_for('community.profile'))


@community_bp.route('/profile/verification-status')
@login_required
def verification_status():
    """API endpoint to get verification status for all categories."""
    if current_user.role != 'community':
        return jsonify({'error': 'Access denied'}), 403
    
    community_profile = CommunityUsers.query.filter_by(user_id=current_user.id).first()
    
    if not community_profile:
        return jsonify({'error': 'Profile not found'}), 404
    
    return jsonify({
        'senior_citizen': {
            'status': community_profile.senior_citizen_verification or 'none',
            'id_number': community_profile.senior_citizen_id_number,
            'eligible': community_profile.age is not None and community_profile.age >= 60
        },
        'pwd': {
            'status': community_profile.pwd_verification or 'none',
            'id_number': community_profile.pwd_id_number,
            'eligible': community_profile.is_pwd
        },
        'solo_parent': {
            'status': community_profile.solo_parent_verification or 'none',
            'id_number': community_profile.solo_parent_id_number,
            'eligible': community_profile.is_solo_parent
        }
    })


@community_bp.route('/activity-logs')
@login_required
def activity_logs():
    """Display user's own activity logs."""
    if current_user.role != 'community':
        flash('Access denied. This page is for community users only.', 'error')
        return redirect(url_for('home.index'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = UserActivityLog.query.filter_by(user_id=current_user.id)
    
    # Filters
    action_type = request.args.get('action_type', '').strip()
    if action_type:
        query = query.filter(UserActivityLog.action_type == action_type)
    
    entity_type = request.args.get('entity_type', '').strip()
    if entity_type:
        query = query.filter(UserActivityLog.entity_type == entity_type)
    
    date_range = request.args.get('date_range', '').strip()
    if date_range == 'today':
        from datetime import datetime, timedelta
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(UserActivityLog.created_at >= start)
    elif date_range == 'week':
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(UserActivityLog.created_at >= start)
    elif date_range == 'month':
        from datetime import datetime
        now = datetime.utcnow()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(UserActivityLog.created_at >= start)
    
    pagination = query.order_by(UserActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('community/activity_logs.html',
                         activities=pagination.items,
                         pagination=pagination,
                         user=current_user)
