from flask import render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
import secrets
import string
import csv
import io
from app.admin import admin_bp
from app.models import (
    User,
    AdminUsers,
    Notifications,
    Applications,
    Programs,
    Announcements,
    AdminActivityLog,
    UserActivityLog,
    find_existing_user_by_name,
)
from app.extensions import db
from app.utils import role_required, manila_strftime
from app.activity_logger import log_admin_management
from app.location_options import get_municipalities, is_valid_municipality

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
            User.email.contains(search),
            User.admin_profile.has(AdminUsers.municipality.ilike(f'%{search}%'))
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
        admin.municipality = admin.admin_profile.municipality if admin.admin_profile and admin.admin_profile.municipality else 'Not set'
    
    # Get recent activity logs from database
    recent_activities = get_recent_admin_activities(limit=20)
    
    return render_template(
        'admin/admin_management.html',
        admins=pagination.items,
        pagination=pagination,
        total_admins=total_admins,
        active_admins=active_admins,
        new_this_month=new_this_month,
        recent_activities=recent_activities,
        municipalities=get_municipalities(),
        user=current_user
    )

@admin_bp.route('/admin_management/add', methods=['POST'])
@login_required
@role_required('admin')
def add_admin():
    """Add a new admin user"""
    email = request.form.get('email', '').strip().lower()
    first_name = request.form.get('first_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    municipality = request.form.get('municipality', '').strip()
    
    # Validation
    if not email or not first_name or not last_name or not municipality:
        flash('Email, first name, last name, and municipality are required.', 'danger')
        return redirect(url_for('admin.admin_management'))

    if not is_valid_municipality(municipality):
        flash('Please select a valid municipality.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    existing_name_user = find_existing_user_by_name(first_name, middle_name, last_name)
    if existing_name_user:
        flash('A user with the same first, middle, and last name already exists.', 'danger')
        return redirect(url_for('admin.admin_management'))

    # Check if email already exists
    existing_user = User.query.filter(func.lower(User.email) == email).first()
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
            municipality=municipality,
            created_at=datetime.utcnow()
        )
        db.session.add(admin_profile)
        
        # Create notification for new admin
        notification = Notifications(
            user_id=new_admin.id,
            notif_title='Welcome to AYUDA Admin',
            notif_message=f'Your admin account has been created. Your temporary password has been sent to your registered email. Please change it after logging in.',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        
        db.session.commit()
        
        flash(
            f'Admin account created successfully for {first_name} {last_name}. '
            f'Temporary password/reset code: {temp_password}',
            'success'
        )
        
        # Log activity
        log_admin_management(new_admin, 'create')
        db.session.commit()
        
    except IntegrityError:
        db.session.rollback()
        flash(f'User with email {email} already exists.', 'danger')
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
    email = request.form.get('email', '').strip().lower()
    municipality = request.form.get('municipality', '').strip()
    
    # Validation
    if not first_name or not last_name or not email or not municipality:
        flash('First name, last name, email, and municipality are required.', 'danger')
        return redirect(url_for('admin.admin_management'))

    if not is_valid_municipality(municipality):
        flash('Please select a valid municipality.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    # Check if email is taken by another user
    existing_user = User.query.filter(func.lower(User.email) == email, User.id != admin_id).first()
    if existing_user:
        flash(f'Email {email} is already taken by another user.', 'danger')
        return redirect(url_for('admin.admin_management'))
    
    try:
        old_email = admin_user.email
        
        admin_user.first_name = first_name
        admin_user.middle_name = middle_name
        admin_user.last_name = last_name
        admin_user.email = email

        if not admin_user.admin_profile:
            admin_user.admin_profile = AdminUsers(user_id=admin_user.id, created_at=datetime.utcnow())
        admin_user.admin_profile.municipality = municipality
        
        db.session.commit()
        
        flash(f'Admin account updated successfully for {first_name} {last_name}.', 'success')
        
        # Log activity
        log_admin_management(admin_user, 'update', {'old_email': old_email})
        db.session.commit()
        
    except IntegrityError:
        db.session.rollback()
        flash(f'Email {email} is already taken by another user.', 'danger')
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
    
    # Generate temporary reset code
    reset_code = ''.join(secrets.choice(string.digits) for _ in range(8))
    
    try:
        admin_user.password_hash = generate_password_hash(reset_code, method='pbkdf2:sha256')
        
        # Send reset code to the target admin via in-app notification.
        notification = Notifications(
            user_id=admin_id,
            notif_title='Password Reset',
            notif_message=(
                f'Your password has been reset by an administrator. '
                f'Your temporary password/reset code is: {reset_code}. '
                f'Use this code to log in. It is strongly recommended that you change your password immediately.'
            ),
            related_type='admin_alert',
            created_at=datetime.utcnow()
        )
        db.session.add(notification)

        # Log reset activity as part of the same transaction.
        log_admin_management(admin_user, 'reset_password', {
            'reset_code_delivery': 'notification_and_flash',
            'reset_code_length': len(reset_code)
        })
        
        db.session.commit()
        
        flash(
            f'Password reset successfully for {admin_user.first_name} {admin_user.last_name}. '
            f'New temporary password/reset code: {reset_code}',
            'success'
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
        
        # Log activity before commit
        from app.activity_logger import log_activity
        log_activity(
            action='delete_admin',
            action_type='delete',
            entity_type='admin',
            description=f'Deleted admin account: {admin_name} ({admin_email})',
            details={'admin_name': admin_name, 'admin_email': admin_email}
        )
        
        db.session.commit()
        
        flash(f'Admin account for {admin_name} deleted successfully.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting admin account: {str(e)}', 'danger')
    
    return redirect(url_for('admin.admin_management'))

def get_recent_admin_activities(limit=20):
    """
    Get recent admin activities from the database.
    Returns list of AdminActivityLog entries.
    """
    try:
        activities = AdminActivityLog.query\
            .order_by(AdminActivityLog.created_at.desc())\
            .limit(limit)\
            .all()
        
        result = []
        for activity in activities:
            result.append({
                'id': activity.id,
                'admin_name': activity.admin_name,
                'action': activity.action.replace('_', ' ').title(),
                'description': activity.description,
                'timestamp': activity.created_at,
                'action_type': activity.action_type
            })
        
        return result
    except Exception as e:
        print(f"[ACTIVITY LOG] Error fetching activities: {e}")
        return []


@admin_bp.route('/activity-logs')
@login_required
@role_required('admin')
def activity_logs():
    """Full activity logs page with filtering and pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 25
    
    # Build query
    query = AdminActivityLog.query
    
    # Apply filters
    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(AdminActivityLog.description.ilike(f'%{search}%'))
    
    action_type = request.args.get('action_type', '').strip()
    if action_type:
        query = query.filter(AdminActivityLog.action_type == action_type)
    
    entity_type = request.args.get('entity_type', '').strip()
    if entity_type:
        query = query.filter(AdminActivityLog.entity_type == entity_type)
    
    admin_id = request.args.get('admin_id', '', type=str).strip()
    if admin_id:
        query = query.filter(AdminActivityLog.admin_id == int(admin_id))
    
    date_range = request.args.get('date_range', '').strip()
    now = datetime.utcnow()
    if date_range == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(AdminActivityLog.created_at >= start)
    elif date_range == 'week':
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(AdminActivityLog.created_at >= start)
    elif date_range == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(AdminActivityLog.created_at >= start)
    elif date_range == 'quarter':
        quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(AdminActivityLog.created_at >= start)
    
    # Get total count (with filters applied)
    total_activities = query.count()
    
    # Stats
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = AdminActivityLog.query.filter(AdminActivityLog.created_at >= today_start).count()
    
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_count = AdminActivityLog.query.filter(AdminActivityLog.created_at >= week_start).count()
    
    active_admins = db.session.query(func.count(func.distinct(AdminActivityLog.admin_id)))\
        .filter(AdminActivityLog.created_at >= week_start).scalar() or 0
    
    # Paginate
    pagination = query.order_by(AdminActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Get admin users for filter dropdown
    admins = User.query.filter(User.role == 'admin').order_by(User.first_name).all()
    
    return render_template('admin/activity_logs.html',
        activities=pagination.items,
        pagination=pagination,
        total_activities=total_activities,
        today_count=today_count,
        week_count=week_count,
        active_admins=active_admins,
        admins=admins
    )


@admin_bp.route('/activity-logs/export')
@login_required
@role_required('admin')
def export_activity_logs():
    """Export activity logs as CSV."""
    # Build query with same filters as the main page
    query = AdminActivityLog.query
    
    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(AdminActivityLog.description.ilike(f'%{search}%'))
    
    action_type = request.args.get('action_type', '').strip()
    if action_type:
        query = query.filter(AdminActivityLog.action_type == action_type)
    
    entity_type = request.args.get('entity_type', '').strip()
    if entity_type:
        query = query.filter(AdminActivityLog.entity_type == entity_type)
    
    admin_id = request.args.get('admin_id', '', type=str).strip()
    if admin_id:
        query = query.filter(AdminActivityLog.admin_id == int(admin_id))
    
    activities = query.order_by(AdminActivityLog.created_at.desc()).all()
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date & Time', 'Admin', 'Action', 'Action Type', 'Entity Type', 'Entity ID', 'Description', 'IP Address'])
    
    for a in activities:
        writer.writerow([
            manila_strftime(a.created_at, '%Y-%m-%d %H:%M:%S', ''),
            a.admin_name,
            a.action,
            a.action_type,
            a.entity_type,
            a.entity_id or '',
            a.description,
            a.ip_address or ''
        ])
    
    output.seek(0)
    timestamp = manila_strftime(datetime.utcnow(), '%Y%m%d_%H%M%S', '')
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=activity_logs_{timestamp}.csv'}
    )


@admin_bp.route('/user-activity-logs')
@login_required
@role_required('admin')
def user_activity_logs():
    """View community user activity logs."""
    page = request.args.get('page', 1, type=int)
    per_page = 30
    
    query = UserActivityLog.query
    
    # Filters
    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(UserActivityLog.description.ilike(f'%{search}%'))
    
    action_type = request.args.get('action_type', '').strip()
    if action_type:
        query = query.filter(UserActivityLog.action_type == action_type)
    
    entity_type = request.args.get('entity_type', '').strip()
    if entity_type:
        query = query.filter(UserActivityLog.entity_type == entity_type)
    
    user_id = request.args.get('user_id', '').strip()
    if user_id:
        query = query.filter(UserActivityLog.user_id == int(user_id))
    
    date_range = request.args.get('date_range', '').strip()
    now = datetime.utcnow()
    if date_range == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(UserActivityLog.created_at >= start)
    elif date_range == 'week':
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(UserActivityLog.created_at >= start)
    elif date_range == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(UserActivityLog.created_at >= start)
    
    total_activities = query.count()
    
    # Stats
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = UserActivityLog.query.filter(UserActivityLog.created_at >= today_start).count()
    
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_count = UserActivityLog.query.filter(UserActivityLog.created_at >= week_start).count()
    
    active_users = db.session.query(func.count(func.distinct(UserActivityLog.user_id)))\
        .filter(UserActivityLog.created_at >= week_start).scalar() or 0
    
    pagination = query.order_by(UserActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Get community users for filter
    community_users = User.query.filter(User.role == 'community').order_by(User.first_name).all()
    
    return render_template('admin/user_activity_logs.html',
        activities=pagination.items,
        pagination=pagination,
        total_activities=total_activities,
        today_count=today_count,
        week_count=week_count,
        active_users=active_users,
        community_users=community_users
    )


@admin_bp.route('/user-activity-logs/export')
@login_required
@role_required('admin')
def export_user_activity_logs():
    """Export user activity logs as CSV."""
    query = UserActivityLog.query
    
    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(UserActivityLog.description.ilike(f'%{search}%'))
    
    action_type = request.args.get('action_type', '').strip()
    if action_type:
        query = query.filter(UserActivityLog.action_type == action_type)
    
    entity_type = request.args.get('entity_type', '').strip()
    if entity_type:
        query = query.filter(UserActivityLog.entity_type == entity_type)
    
    activities = query.order_by(UserActivityLog.created_at.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date & Time', 'User', 'Action', 'Action Type', 'Entity Type', 'Entity ID', 'Description', 'IP Address'])
    
    for a in activities:
        writer.writerow([
            manila_strftime(a.created_at, '%Y-%m-%d %H:%M:%S', ''),
            a.user_name,
            a.action,
            a.action_type,
            a.entity_type,
            a.entity_id or '',
            a.description,
            a.ip_address or ''
        ])
    
    output.seek(0)
    timestamp = manila_strftime(datetime.utcnow(), '%Y%m%d_%H%M%S', '')
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=user_activity_logs_{timestamp}.csv'}
    )
