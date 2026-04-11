from flask import render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc, or_, func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
import secrets
import string
import csv
import io

from app.activity_logger import log_admin_management
from app.extensions import db
from app.location_options import get_municipalities, is_valid_municipality
from app.models import (
    AdminActivityLog,
    AdminUsers,
    Announcements,
    Applications,
    Notifications,
    Programs,
    User,
    UserActivityLog,
)
from app.super_admin import super_admin_bp
from app.utils import manila_strftime, role_required


@super_admin_bp.route('/admin-management')
@super_admin_bp.route('/admin_management')
@login_required
@role_required('super_admin')
def admin_management():
    """Display all admin users with activity log for super admins."""
    page = request.args.get('page', 1, type=int)
    per_page = 10

    search = request.args.get('search', '').strip()
    municipality_filter = request.args.get('municipality', '').strip()

    query = User.query.filter_by(role='admin')

    if search:
        search_filter = or_(
            User.first_name.contains(search),
            User.last_name.contains(search),
            User.email.contains(search),
            User.admin_profile.has(AdminUsers.municipality.ilike(f'%{search}%')),
        )
        query = query.filter(search_filter)

    if municipality_filter:
        query = query.filter(User.admin_profile.has(AdminUsers.municipality == municipality_filter))

    query = query.order_by(desc(User.created_at))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    stats_query = User.query.filter_by(role='admin')
    if municipality_filter:
        stats_query = stats_query.filter(User.admin_profile.has(AdminUsers.municipality == municipality_filter))

    total_admins = stats_query.count()

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    active_admins = stats_query.filter(User.last_activity >= seven_days_ago).count()

    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = stats_query.filter(User.created_at >= start_of_month).count()

    for admin in pagination.items:
        admin.programs_created = Programs.query.filter_by(user_id=admin.id).count()
        admin.announcements_created = Announcements.query.filter_by(author_id=admin.id).count()
        admin.applications_reviewed = Applications.query.filter_by(reviewed_by=admin.id).count()
        admin.municipality = admin.admin_profile.municipality if admin.admin_profile and admin.admin_profile.municipality else 'Not set'

    return render_template(
        'super_admin/admin_management.html',
        admins=pagination.items,
        pagination=pagination,
        total_admins=total_admins,
        active_admins=active_admins,
        new_this_month=new_this_month,
        municipalities=get_municipalities(),
        user=current_user,
    )


@super_admin_bp.route('/admin-management/add', methods=['POST'])
@login_required
@role_required('super_admin')
def add_admin():
    """Add a new admin user."""
    email = request.form.get('email', '').strip().lower()
    first_name = request.form.get('first_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    municipality = request.form.get('municipality', '').strip()
    redirect_next = (request.form.get('redirect_next') or '').strip()
    redirect_target = redirect_next if redirect_next.startswith('/') else url_for('super_admin.admin_management')

    if not email or not first_name or not last_name or not municipality:
        flash('Email, first name, last name, and municipality are required.', 'danger')
        return redirect(redirect_target)

    if not is_valid_municipality(municipality):
        flash('Please select a valid municipality.', 'danger')
        return redirect(redirect_target)

    existing_user = User.query.filter(func.lower(User.email) == email).first()
    if existing_user:
        flash(f'User with email {email} already exists.', 'danger')
        return redirect(redirect_target)

    temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

    try:
        new_admin = User(
            email=email,
            password_hash=generate_password_hash(temp_password, method='pbkdf2:sha256'),
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            role='admin',
            created_at=datetime.utcnow(),
        )
        db.session.add(new_admin)
        db.session.flush()

        admin_profile = AdminUsers(
            user_id=new_admin.id,
            municipality=municipality,
            created_at=datetime.utcnow(),
        )
        db.session.add(admin_profile)

        notification = Notifications(
            user_id=new_admin.id,
            notif_title='Welcome to AYUDA Admin',
            notif_message=(
                'Your admin account has been created. Your temporary password has been '
                'sent to your registered email. Please change it after logging in.'
            ),
            created_at=datetime.utcnow(),
        )
        db.session.add(notification)

        db.session.commit()

        flash(
            f'Admin account created successfully for {first_name} {last_name}. '
            f'Temporary password/reset code: {temp_password}',
            'success',
        )

        log_admin_management(new_admin, 'create')
        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        flash(f'User with email {email} already exists.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating admin account: {str(e)}', 'danger')

    return redirect(redirect_target)


@super_admin_bp.route('/admin-management/edit/<int:admin_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def edit_admin(admin_id):
    """Edit an admin user."""
    admin_user = User.query.filter_by(id=admin_id, role='admin').first_or_404()

    if admin_user.id == current_user.id:
        flash('Cannot edit your own account through this interface. Use profile settings.', 'warning')
        return redirect(url_for('super_admin.admin_management'))

    first_name = request.form.get('first_name', '').strip()
    middle_name = request.form.get('middle_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    municipality = request.form.get('municipality', '').strip()

    if not first_name or not last_name or not email or not municipality:
        flash('First name, last name, email, and municipality are required.', 'danger')
        return redirect(url_for('super_admin.admin_management'))

    if not is_valid_municipality(municipality):
        flash('Please select a valid municipality.', 'danger')
        return redirect(url_for('super_admin.admin_management'))

    existing_user = User.query.filter(func.lower(User.email) == email, User.id != admin_id).first()
    if existing_user:
        flash(f'Email {email} is already taken by another user.', 'danger')
        return redirect(url_for('super_admin.admin_management'))

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

        log_admin_management(admin_user, 'update', {'old_email': old_email})
        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        flash(f'Email {email} is already taken by another user.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating admin account: {str(e)}', 'danger')

    return redirect(url_for('super_admin.admin_management'))


@super_admin_bp.route('/admin-management/reset-password/<int:admin_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def reset_admin_password(admin_id):
    """Reset an admin's password."""
    admin_user = User.query.filter_by(id=admin_id, role='admin').first_or_404()

    reset_code = ''.join(secrets.choice(string.digits) for _ in range(8))

    try:
        admin_user.password_hash = generate_password_hash(reset_code, method='pbkdf2:sha256')

        notification = Notifications(
            user_id=admin_id,
            notif_title='Password Reset',
            notif_message=(
                'Your password has been reset by an administrator. '
                f'Your temporary password/reset code is: {reset_code}. '
                'Use this code to log in. It is strongly recommended that you '
                'change your password immediately.'
            ),
            related_type='admin_alert',
            created_at=datetime.utcnow(),
        )
        db.session.add(notification)

        log_admin_management(admin_user, 'reset_password', {
            'reset_code_delivery': 'notification_and_flash',
            'reset_code_length': len(reset_code),
        })

        db.session.commit()

        flash(
            f'Password reset successfully for {admin_user.first_name} {admin_user.last_name}. '
            f'New temporary password/reset code: {reset_code}',
            'success',
        )

    except Exception as e:
        db.session.rollback()
        flash(f'Error resetting password: {str(e)}', 'danger')

    return redirect(url_for('super_admin.admin_management'))


@super_admin_bp.route('/admin-management/delete/<int:admin_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_admin(admin_id):
    """Delete an admin user."""
    admin_user = User.query.filter_by(id=admin_id, role='admin').first_or_404()

    if admin_user.id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('super_admin.admin_management'))

    admin_count = User.query.filter_by(role='admin').count()
    if admin_count <= 1:
        flash('Cannot delete the last admin account.', 'danger')
        return redirect(url_for('super_admin.admin_management'))

    try:
        admin_name = f"{admin_user.first_name} {admin_user.last_name}"
        admin_email = admin_user.email

        if admin_user.admin_profile:
            db.session.delete(admin_user.admin_profile)

        Notifications.query.filter_by(user_id=admin_id).delete()
        db.session.delete(admin_user)

        from app.activity_logger import log_activity

        log_activity(
            action='delete_admin',
            action_type='delete',
            entity_type='admin',
            description=f'Deleted admin account: {admin_name} ({admin_email})',
            details={'admin_name': admin_name, 'admin_email': admin_email},
        )

        db.session.commit()

        flash(f'Admin account for {admin_name} deleted successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting admin account: {str(e)}', 'danger')

    return redirect(url_for('super_admin.admin_management'))


def get_recent_admin_activities(limit=20):
    """Get recent admin activities from the database."""
    try:
        activities = (
            AdminActivityLog.query
            .order_by(AdminActivityLog.created_at.desc())
            .limit(limit)
            .all()
        )

        result = []
        for activity in activities:
            result.append({
                'id': activity.id,
                'admin_name': activity.admin_name,
                'action': activity.action.replace('_', ' ').title(),
                'description': activity.description,
                'timestamp': activity.created_at,
                'action_type': activity.action_type,
            })

        return result
    except Exception as e:
        print(f"[ACTIVITY LOG] Error fetching activities: {e}")
        return []


@super_admin_bp.route('/admin-management/activity-logs')
@login_required
@role_required('super_admin')
def activity_logs():
    """Full admin activity logs page with filtering and pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 25

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

    total_activities = query.count()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = AdminActivityLog.query.filter(AdminActivityLog.created_at >= today_start).count()

    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_count = AdminActivityLog.query.filter(AdminActivityLog.created_at >= week_start).count()

    active_admins = (
        db.session.query(func.count(func.distinct(AdminActivityLog.admin_id)))
        .filter(AdminActivityLog.created_at >= week_start)
        .scalar()
        or 0
    )

    pagination = query.order_by(AdminActivityLog.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    admins = User.query.filter(User.role == 'admin').order_by(User.first_name).all()

    return render_template(
        'admin/activity_logs.html',
        activities=pagination.items,
        pagination=pagination,
        total_activities=total_activities,
        today_count=today_count,
        week_count=week_count,
        active_admins=active_admins,
        admins=admins,
        logs_endpoint='super_admin.activity_logs',
        export_endpoint='super_admin.export_activity_logs',
        scope_label='Global scope: all municipalities',
    )


@super_admin_bp.route('/admin-management/activity-logs/export')
@login_required
@role_required('super_admin')
def export_activity_logs():
    """Export admin activity logs as CSV."""
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

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date & Time', 'Admin', 'Action', 'Action Type', 'Entity Type', 'Entity ID', 'Description', 'IP Address'])

    for activity in activities:
        writer.writerow([
            manila_strftime(activity.created_at, '%Y-%m-%d %H:%M:%S', ''),
            activity.admin_name,
            activity.action,
            activity.action_type,
            activity.entity_type,
            activity.entity_id or '',
            activity.description,
            activity.ip_address or '',
        ])

    output.seek(0)
    timestamp = manila_strftime(datetime.utcnow(), '%Y%m%d_%H%M%S', '')
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=activity_logs_{timestamp}.csv'},
    )


@super_admin_bp.route('/admin-management/user-activity-logs')
@login_required
@role_required('super_admin')
def user_activity_logs():
    """View community user activity logs."""
    page = request.args.get('page', 1, type=int)
    per_page = 30

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

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = UserActivityLog.query.filter(UserActivityLog.created_at >= today_start).count()

    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_count = UserActivityLog.query.filter(UserActivityLog.created_at >= week_start).count()

    active_users = (
        db.session.query(func.count(func.distinct(UserActivityLog.user_id)))
        .filter(UserActivityLog.created_at >= week_start)
        .scalar()
        or 0
    )

    pagination = query.order_by(UserActivityLog.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    community_users = User.query.filter(User.role == 'community').order_by(User.first_name).all()

    return render_template(
        'admin/user_activity_logs.html',
        activities=pagination.items,
        pagination=pagination,
        total_activities=total_activities,
        today_count=today_count,
        week_count=week_count,
        active_users=active_users,
        community_users=community_users,
        logs_endpoint='super_admin.user_activity_logs',
        export_endpoint='super_admin.export_user_activity_logs',
        scope_label='Global scope: all municipalities',
    )


@super_admin_bp.route('/admin-management/user-activity-logs/export')
@login_required
@role_required('super_admin')
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

    for activity in activities:
        writer.writerow([
            manila_strftime(activity.created_at, '%Y-%m-%d %H:%M:%S', ''),
            activity.user_name,
            activity.action,
            activity.action_type,
            activity.entity_type,
            activity.entity_id or '',
            activity.description,
            activity.ip_address or '',
        ])

    output.seek(0)
    timestamp = manila_strftime(datetime.utcnow(), '%Y%m%d_%H%M%S', '')
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=user_activity_logs_{timestamp}.csv'},
    )
