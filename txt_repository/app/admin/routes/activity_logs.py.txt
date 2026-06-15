from datetime import datetime, timedelta
import csv
import io

from flask import Response, flash, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func

from app.admin import admin_bp
from app.extensions import db
from app.models import AdminActivityLog, AdminUsers, CommunityUsers, User, UserActivityLog
from app.utils import manila_strftime, role_required


def _current_admin_municipality():
    profile = getattr(current_user, 'admin_profile', None)
    municipality = (profile.municipality or '').strip() if profile else ''
    return municipality or None


@admin_bp.route('/activity-logs')
@login_required
@role_required('admin')
def activity_logs():
    """Municipality-scoped admin activity logs for regular admins."""
    admin_municipality = _current_admin_municipality()
    if not admin_municipality:
        flash('Admin profile is missing municipality. Activity logs cannot be scoped.', 'warning')
        return render_template(
            'admin/activity_logs.html',
            activities=[],
            pagination=None,
            total_activities=0,
            today_count=0,
            week_count=0,
            active_admins=0,
            admins=[],
            logs_endpoint='admin.activity_logs',
            export_endpoint='admin.export_activity_logs',
            scope_label='Your municipality is not set',
        )

    page = request.args.get('page', 1, type=int)
    per_page = 25

    query = (
        AdminActivityLog.query
        .join(User, User.id == AdminActivityLog.admin_id)
        .join(AdminUsers, AdminUsers.user_id == User.id)
        .filter(User.role == 'admin', AdminUsers.municipality == admin_municipality)
    )

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
    today_count = (
        AdminActivityLog.query
        .join(User, User.id == AdminActivityLog.admin_id)
        .join(AdminUsers, AdminUsers.user_id == User.id)
        .filter(
            User.role == 'admin',
            AdminUsers.municipality == admin_municipality,
            AdminActivityLog.created_at >= today_start,
        )
        .count()
    )

    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_count = (
        AdminActivityLog.query
        .join(User, User.id == AdminActivityLog.admin_id)
        .join(AdminUsers, AdminUsers.user_id == User.id)
        .filter(
            User.role == 'admin',
            AdminUsers.municipality == admin_municipality,
            AdminActivityLog.created_at >= week_start,
        )
        .count()
    )

    active_admins = (
        db.session.query(func.count(func.distinct(AdminActivityLog.admin_id)))
        .join(User, User.id == AdminActivityLog.admin_id)
        .join(AdminUsers, AdminUsers.user_id == User.id)
        .filter(
            User.role == 'admin',
            AdminUsers.municipality == admin_municipality,
            AdminActivityLog.created_at >= week_start,
        )
        .scalar()
        or 0
    )

    pagination = query.order_by(AdminActivityLog.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    admins = (
        User.query
        .join(AdminUsers, AdminUsers.user_id == User.id)
        .filter(User.role == 'admin', AdminUsers.municipality == admin_municipality)
        .order_by(User.first_name)
        .all()
    )

    return render_template(
        'admin/activity_logs.html',
        activities=pagination.items,
        pagination=pagination,
        total_activities=total_activities,
        today_count=today_count,
        week_count=week_count,
        active_admins=active_admins,
        admins=admins,
        logs_endpoint='admin.activity_logs',
        export_endpoint='admin.export_activity_logs',
        scope_label=f'Municipality scope: {admin_municipality}',
    )


@admin_bp.route('/activity-logs/export')
@login_required
@role_required('admin')
def export_activity_logs():
    """Export municipality-scoped admin activity logs as CSV."""
    admin_municipality = _current_admin_municipality()
    if not admin_municipality:
        flash('Admin profile is missing municipality. Nothing to export.', 'warning')
        return Response('', mimetype='text/csv')

    query = (
        AdminActivityLog.query
        .join(User, User.id == AdminActivityLog.admin_id)
        .join(AdminUsers, AdminUsers.user_id == User.id)
        .filter(User.role == 'admin', AdminUsers.municipality == admin_municipality)
    )

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
    writer.writerow([
        'Date & Time',
        'Municipality Scope',
        'Admin',
        'Action',
        'Action Type',
        'Entity Type',
        'Entity ID',
        'Description',
        'IP Address',
    ])

    for activity in activities:
        writer.writerow([
            manila_strftime(activity.created_at, '%Y-%m-%d %H:%M:%S', ''),
            admin_municipality,
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
        headers={'Content-Disposition': f'attachment; filename=municipality_admin_activity_logs_{timestamp}.csv'},
    )


@admin_bp.route('/user-activity-logs')
@login_required
@role_required('admin')
def user_activity_logs():
    """Municipality-scoped community activity logs for regular admins."""
    admin_municipality = _current_admin_municipality()
    if not admin_municipality:
        flash('Admin profile is missing municipality. Activity logs cannot be scoped.', 'warning')
        return render_template(
            'admin/user_activity_logs.html',
            activities=[],
            pagination=None,
            total_activities=0,
            today_count=0,
            week_count=0,
            active_users=0,
            community_users=[],
            logs_endpoint='admin.user_activity_logs',
            export_endpoint='admin.export_user_activity_logs',
            scope_label='Your municipality is not set',
        )

    page = request.args.get('page', 1, type=int)
    per_page = 30

    query = (
        UserActivityLog.query
        .join(User, User.id == UserActivityLog.user_id)
        .join(CommunityUsers, CommunityUsers.user_id == User.id)
        .filter(User.role == 'community', CommunityUsers.municipality == admin_municipality)
    )

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
    today_count = (
        UserActivityLog.query
        .join(User, User.id == UserActivityLog.user_id)
        .join(CommunityUsers, CommunityUsers.user_id == User.id)
        .filter(
            User.role == 'community',
            CommunityUsers.municipality == admin_municipality,
            UserActivityLog.created_at >= today_start,
        )
        .count()
    )

    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_count = (
        UserActivityLog.query
        .join(User, User.id == UserActivityLog.user_id)
        .join(CommunityUsers, CommunityUsers.user_id == User.id)
        .filter(
            User.role == 'community',
            CommunityUsers.municipality == admin_municipality,
            UserActivityLog.created_at >= week_start,
        )
        .count()
    )

    active_users = (
        db.session.query(func.count(func.distinct(UserActivityLog.user_id)))
        .join(User, User.id == UserActivityLog.user_id)
        .join(CommunityUsers, CommunityUsers.user_id == User.id)
        .filter(
            User.role == 'community',
            CommunityUsers.municipality == admin_municipality,
            UserActivityLog.created_at >= week_start,
        )
        .scalar()
        or 0
    )

    pagination = query.order_by(UserActivityLog.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    community_users = (
        User.query
        .join(CommunityUsers, CommunityUsers.user_id == User.id)
        .filter(User.role == 'community', CommunityUsers.municipality == admin_municipality)
        .order_by(User.first_name)
        .all()
    )

    return render_template(
        'admin/user_activity_logs.html',
        activities=pagination.items,
        pagination=pagination,
        total_activities=total_activities,
        today_count=today_count,
        week_count=week_count,
        active_users=active_users,
        community_users=community_users,
        logs_endpoint='admin.user_activity_logs',
        export_endpoint='admin.export_user_activity_logs',
        scope_label=f'Municipality scope: {admin_municipality}',
    )


@admin_bp.route('/user-activity-logs/export')
@login_required
@role_required('admin')
def export_user_activity_logs():
    """Export municipality-scoped community user activity logs as CSV."""
    admin_municipality = _current_admin_municipality()
    if not admin_municipality:
        flash('Admin profile is missing municipality. Nothing to export.', 'warning')
        return Response('', mimetype='text/csv')

    query = (
        UserActivityLog.query
        .join(User, User.id == UserActivityLog.user_id)
        .join(CommunityUsers, CommunityUsers.user_id == User.id)
        .filter(User.role == 'community', CommunityUsers.municipality == admin_municipality)
    )

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

    activities = query.order_by(UserActivityLog.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date & Time',
        'Municipality Scope',
        'User',
        'Action',
        'Action Type',
        'Entity Type',
        'Entity ID',
        'Description',
        'IP Address',
    ])

    for activity in activities:
        writer.writerow([
            manila_strftime(activity.created_at, '%Y-%m-%d %H:%M:%S', ''),
            admin_municipality,
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
        headers={'Content-Disposition': f'attachment; filename=municipality_user_activity_logs_{timestamp}.csv'},
    )
