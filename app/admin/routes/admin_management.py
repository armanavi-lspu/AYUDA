from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from werkzeug.security import generate_password_hash
import secrets
import string
from app.admin import admin_bp
from app.models import User, AdminUsers, Notifications, Applications, Programs, Announcements
from app.extensions import db
from app.utils import role_required

@admin_bp.route('/admin_management')
@login_required
@role_required('admin')
def admin_management():
    """Display all admin users with activity log"""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    date_range = request.args.get('date_range', '').strip()
    
    # Base query - only admin users
    query = User.query.filter_by(role='admin')
    
    # Apply search filter
    if search:
        search_filter = or_(
            User.first_name.contains(search),
            User.last_name.contains(search),
            User.email.contains(search)
        )
        query = query.filter(search_filter)
    
    # Apply date range filter
    if date_range:
        today = datetime.utcnow()
        if date_range == 'today':
            start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.filter(User.created_at >= start_date)
        elif date_range == 'week':
            start_date = today - timedelta(days=7)
            query = query.filter(User.created_at >= start_date)
        elif date_range == 'month':
            start_date = today - timedelta(days=30)
            query = query.filter(User.created_at >= start_date)
        elif date_range == 'year':
            start_date = today - timedelta(days=365)
            query = query.filter(User.created_at >= start_date)
    
    # Order by creation date (newest first)
    query = query.order_by(desc(User.created_at))
    
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get statistics
    total_admins = User.query.filter_by(role='admin').count()
    
    # Active admins (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    active_admins = User.query.filter(
        User.role == 'admin',
        User.last_activity >= seven_days_ago
    ).count()
    
    # New admins this month
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = User.query.filter(
        User.role == 'admin',
        User.created_at >= start_of_month
    ).count()
    
    # Add activity counts to each admin
    for admin in pagination.items:
        admin.programs_created = Programs.query.filter_by(user_id=admin.id).count()
        admin.announcements_created = Announcements.query.filter_by(author_id=admin.id).count()
        admin.applications_reviewed = Applications.query.filter_by(reviewed_by=admin.id).count()
    
    # Get recent activity logs (outline - will be implemented with ActivityLog model)
    recent_activities = get_recent_admin_activities(limit=20)
    
    return render_template(
        'admin/admin_management.html',
        admins=pagination.items,
        pagination=pagination,
        total_admins=total_admins,
        active_admins=active_admins,
        new_this_month=new_this_month,
        recent_activities=recent_activities,
        user=current_user
    )

@admin_bp.route('/admin_management/add', methods=['POST'])
@login_required
@role_required('admin')
def add_admin():
    """Add a new admin user"""
    email = request.form.get('email', '').strip()
    first_name = request.form.get('first_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    
    # Validation
    if not email or not first_name or not last_name:
        flash('Email, first name, and last name are required.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    # Check if email already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash(f'User with email {email} already exists.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    # Generate random password
    temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    
    try:
        # Create new admin user
        new_admin = User(
            email=email,
            password_hash=generate_password_hash(temp_password, method='pbkdf2:sha256'),
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            role='admin',
            created_at=datetime.utcnow()
        )
        db.session.add(new_admin)
        db.session.flush()
        
        # Create admin profile
        admin_profile = AdminUsers(
            user_id=new_admin.id,
            created_at=datetime.utcnow()
        )
        db.session.add(admin_profile)
        
        # Create notification for new admin
        notification = Notifications(
            user_id=new_admin.id,
            notif_title='Welcome to AYUDA Admin',
            notif_message=f'Your admin account has been created. Your temporary password is: {temp_password}. Please change it after logging in.',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        
        db.session.commit()
        
        flash(f'Admin account created successfully for {first_name} {last_name}. Temporary password: {temp_password}', 'success')
        
        # Log activity (outline)
        log_admin_activity(
            admin_id=current_user.id,
            action='create_admin',
            description=f'Created new admin account for {email}'
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating admin account: {str(e)}', 'danger')
    
    return redirect(url_for('admin.admin_management'))

@admin_bp.route('/admin_management/edit/<int:admin_id>', methods=['POST'])
@login_required
@role_required('admin')
def edit_admin(admin_id):
    """Edit an admin user"""
    admin_user = User.query.filter_by(id=admin_id, role='admin').first_or_404()
    
    # Prevent editing own account through this route
    if admin_user.id == current_user.id:
        flash('Cannot edit your own account through this interface. Use profile settings.', 'warning')
        return redirect(url_for('admin.admin_management'))
    
    first_name = request.form.get('first_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    email = request.form.get('email', '').strip()
    
    # Validation
    if not first_name or not last_name or not email:
        flash('First name, last name, and email are required.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    # Check if email is taken by another user
    existing_user = User.query.filter(User.email == email, User.id != admin_id).first()
    if existing_user:
        flash(f'Email {email} is already taken by another user.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    try:
        old_email = admin_user.email
        
        admin_user.first_name = first_name
        admin_user.middle_name = middle_name
        admin_user.last_name = last_name
        admin_user.email = email
        
        db.session.commit()
        
        flash(f'Admin account updated successfully for {first_name} {last_name}.', 'success')
        
        # Log activity (outline)
        log_admin_activity(
            admin_id=current_user.id,
            action='update_admin',
            description=f'Updated admin account {old_email} to {email}'
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating admin account: {str(e)}', 'danger')
    
    return redirect(url_for('admin.admin_management'))

@admin_bp.route('/admin_management/reset-password/<int:admin_id>', methods=['POST'])
@login_required
@role_required('admin')
def reset_admin_password(admin_id):
    """Reset an admin's password"""
    admin_user = User.query.filter_by(id=admin_id, role='admin').first_or_404()
    
    # Generate random password
    new_password = ''.join(secrets.choice(string.digits) for _ in range(8))
    
    try:
        admin_user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
        
        # Create notification
        notification = Notifications(
            user_id=admin_id,
            notif_title='Password Reset',
            notif_message=f'Your password has been reset. Your new temporary password is: {new_password}. Please change it after logging in.',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        
        db.session.commit()
        
        flash(f'Password reset successfully for {admin_user.first_name} {admin_user.last_name}. New password: {new_password}', 'success')
        
        # Log activity (outline)
        log_admin_activity(
            admin_id=current_user.id,
            action='reset_admin_password',
            description=f'Reset password for admin {admin_user.email}'
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error resetting password: {str(e)}', 'danger')
    
    return redirect(url_for('admin.admin_management'))

@admin_bp.route('/admin_management/delete/<int:admin_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_admin(admin_id):
    """Delete an admin user"""
    admin_user = User.query.filter_by(id=admin_id, role='admin').first_or_404()
    
    # Prevent deleting own account
    if admin_user.id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    # Check if this is the last admin
    admin_count = User.query.filter_by(role='admin').count()
    if admin_count <= 1:
        flash('Cannot delete the last admin account.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    try:
        admin_name = f"{admin_user.first_name} {admin_user.last_name}"
        admin_email = admin_user.email
        
        # Delete admin profile
        if admin_user.admin_profile:
            db.session.delete(admin_user.admin_profile)
        
        # Delete notifications
        Notifications.query.filter_by(user_id=admin_id).delete()
        
        # Delete admin user
        db.session.delete(admin_user)
        db.session.commit()
        
        flash(f'Admin account for {admin_name} deleted successfully.', 'success')
        
        # Log activity (outline)
        log_admin_activity(
            admin_id=current_user.id,
            action='delete_admin',
            description=f'Deleted admin account {admin_email}'
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting admin account: {str(e)}', 'danger')
    
    return redirect(url_for('admin.admin_management'))

# Activity Log Helper Functions (Outline - to be implemented with ActivityLog model)
def log_admin_activity(admin_id, action, description, related_id=None):
    """
    Log admin activity for audit trail
    
    TODO: Implement with ActivityLog model
    Model structure:
    - id (PK)
    - admin_id (FK to users)
    - action (string: create, update, delete, approve, reject, etc.)
    - entity_type (string: user, program, application, announcement, etc.)
    - entity_id (integer: ID of affected entity)
    - description (text: human-readable description)
    - ip_address (string)
    - user_agent (string)
    - created_at (datetime)
    """
    # Placeholder for future implementation
    print(f"[ACTIVITY LOG] Admin {admin_id} - {action}: {description}")
    pass

def get_recent_admin_activities(limit=20):
    """
    Get recent admin activities
    
    TODO: Implement with ActivityLog model
    Should return list of activity records with admin info and timestamps
    """
    # Placeholder - return mock data for now
    mock_activities = [
        {
            'id': 1,
            'admin_name': 'System Admin',
            'action': 'Approved Application',
            'description': 'Approved application #1234 for Financial Aid',
            'timestamp': datetime.utcnow() - timedelta(minutes=15),
            'action_type': 'approve'
        },
        {
            'id': 2,
            'admin_name': current_user.first_name + ' ' + current_user.last_name,
            'action': 'Created Program',
            'description': 'Created new program "Healthcare Assistance"',
            'timestamp': datetime.utcnow() - timedelta(hours=2),
            'action_type': 'create'
        },
        {
            'id': 3,
            'admin_name': 'System Admin',
            'action': 'Updated Announcement',
            'description': 'Updated announcement "New Program Launch"',
            'timestamp': datetime.utcnow() - timedelta(hours=5),
            'action_type': 'update'
        },
        {
            'id': 4,
            'admin_name': current_user.first_name + ' ' + current_user.last_name,
            'action': 'Rejected Application',
            'description': 'Rejected application #1233 - Incomplete documents',
            'timestamp': datetime.utcnow() - timedelta(days=1),
            'action_type': 'reject'
        },
        {
            'id': 5,
            'admin_name': 'System Admin',
            'action': 'Added Requirement',
            'description': 'Added new requirement "Barangay Clearance"',
            'timestamp': datetime.utcnow() - timedelta(days=2),
            'action_type': 'create'
        }
    ]
    
    return mock_activities[:limit]
