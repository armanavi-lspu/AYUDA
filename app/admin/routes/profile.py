from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json

from app.admin import admin_bp
from app.models import User, AdminUsers, AdminActivityLog, Applications, Programs, Announcements
from app.extensions import db
from app.utils import role_required
from app.location_options import get_municipalities, is_valid_municipality

PROFILE_UPLOAD_FOLDER = 'static/uploads/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@admin_bp.route('/profile')
@login_required
@role_required('admin')
def admin_profile():
    """Display admin profile & settings page."""
    if not current_user.admin_profile:
        current_user.admin_profile = AdminUsers(user_id=current_user.id, created_at=datetime.utcnow())
        db.session.add(current_user)
        db.session.commit()

    # Stats for this admin
    programs_created = Programs.query.filter_by(user_id=current_user.id).count()
    announcements_created = Announcements.query.filter_by(author_id=current_user.id).count()
    applications_reviewed = Applications.query.filter_by(reviewed_by=current_user.id).count()

    # Recent activity logs
    recent_logs = AdminActivityLog.query.filter_by(
        admin_id=current_user.id
    ).order_by(AdminActivityLog.created_at.desc()).limit(10).all()

    return render_template(
        'admin/profile_settings.html',
        user=current_user,
        programs_created=programs_created,
        announcements_created=announcements_created,
        applications_reviewed=applications_reviewed,
        recent_logs=recent_logs,
        municipalities=get_municipalities()
    )


@admin_bp.route('/profile/update', methods=['POST'])
@login_required
@role_required('admin')
def update_admin_profile():
    """Update admin profile name fields."""
    first_name = request.form.get('first_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    municipality = request.form.get('municipality', '').strip()

    if not first_name or not last_name or not municipality:
        flash('First name, last name, and municipality are required.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    if not is_valid_municipality(municipality):
        flash('Please select a valid municipality.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    current_user.first_name = first_name
    current_user.middle_name = middle_name
    current_user.last_name = last_name

    if not current_user.admin_profile:
        current_user.admin_profile = AdminUsers(user_id=current_user.id, created_at=datetime.utcnow())
    current_user.admin_profile.municipality = municipality

    db.session.commit()
    flash('Profile updated successfully.', 'success')
    return redirect(url_for('admin.admin_profile'))


@admin_bp.route('/profile/change-password', methods=['POST'])
@login_required
@role_required('admin')
def change_admin_password():
    """Change admin password."""
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not check_password_hash(current_user.password_hash, current_password):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    if len(new_password) < 8:
        flash('New password must be at least 8 characters.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    if new_password != confirm_password:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    flash('Password changed successfully.', 'success')
    return redirect(url_for('admin.admin_profile'))


@admin_bp.route('/profile/upload-photo', methods=['POST'])
@login_required
@role_required('admin')
def upload_admin_photo():
    """Upload admin profile photo."""
    if 'profile_pic' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    file = request.files['profile_pic']
    if file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    if not allowed_file(file.filename):
        flash('Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    upload_path = os.path.join(os.getcwd(), PROFILE_UPLOAD_FOLDER)
    os.makedirs(upload_path, exist_ok=True)

    # Store old photo path for logging
    old_photo = current_user.profile_pic

    # Delete old photo if exists
    if current_user.profile_pic:
        old_path = os.path.join(os.getcwd(), current_user.profile_pic.lstrip('/'))
        if os.path.exists(old_path):
            os.remove(old_path)

    ext = file.filename.rsplit('.', 1)[1].lower()
    unique_filename = f"admin_{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
    file.save(os.path.join(upload_path, unique_filename))

    new_photo_path = f'/{PROFILE_UPLOAD_FOLDER}/{unique_filename}'
    current_user.profile_pic = new_photo_path
    db.session.add(current_user)
    
    # Log the activity
    log_entry = AdminActivityLog(
        admin_id=current_user.id,
        action='profile_photo_upload',
        action_type='update',
        entity_type='admin',
        entity_id=current_user.id,
        description=f"Updated profile photo for {current_user.first_name} {current_user.last_name}",
        details=json.dumps({
            'old_photo': old_photo,
            'new_photo': new_photo_path,
            'file_name': unique_filename,
            'file_type': ext
        }),
        ip_address=request.remote_addr,
        created_at=datetime.utcnow()
    )
    db.session.add(log_entry)
    db.session.commit()
    flash('Profile photo updated successfully.', 'success')
    return redirect(url_for('admin.admin_profile'))


@admin_bp.route('/profile/remove-photo', methods=['POST'])
@login_required
@role_required('admin')
def remove_admin_photo():
    """Remove admin profile photo."""
    if current_user.profile_pic:
        old_photo = current_user.profile_pic
        old_path = os.path.join(os.getcwd(), current_user.profile_pic.lstrip('/'))
        if os.path.exists(old_path):
            os.remove(old_path)
        current_user.profile_pic = None
        db.session.add(current_user)
        
        # Log the activity
        log_entry = AdminActivityLog(
            admin_id=current_user.id,
            action='profile_photo_remove',
            action_type='delete',
            entity_type='admin',
            entity_id=current_user.id,
            description=f"Removed profile photo for {current_user.first_name} {current_user.last_name}",
            details=json.dumps({
                'removed_photo': old_photo
            }),
            ip_address=request.remote_addr,
            created_at=datetime.utcnow()
        )
        db.session.add(log_entry)
        db.session.commit()
        flash('Profile photo removed.', 'success')
    return redirect(url_for('admin.admin_profile'))
