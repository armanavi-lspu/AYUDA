from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc, func, or_

from app.admin import admin_bp
from app.models import AdminActivityLog, AdminUsers, User
from app.utils import role_required


def _current_admin_municipality():
    admin_profile = getattr(current_user, 'admin_profile', None)
    if not admin_profile or not admin_profile.municipality:
        return None
    return admin_profile.municipality.strip()


@admin_bp.route('/admins')
@login_required
@role_required('admin')
def admins():
    """Read-only list of admins within the current admin municipality."""
    admin_municipality = _current_admin_municipality()
    if not admin_municipality:
        flash('Your admin account has no municipality assigned. Please update your profile.', 'danger')
        return redirect(url_for('admin.admin_profile'))

    page = request.args.get('page', 1, type=int)
    per_page = 12

    search = request.args.get('search', '').strip()
    date_range = request.args.get('date_range', '').strip()

    query = User.query.join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        AdminUsers.municipality == admin_municipality,
    )

    if search:
        full_name = User.first_name + ' ' + User.last_name
        reverse_full_name = User.last_name + ' ' + User.first_name
        query = query.filter(
            or_(
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
                full_name.ilike(f'%{search}%'),
                reverse_full_name.ilike(f'%{search}%'),
            )
        )

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

    pagination = query.order_by(desc(User.created_at)).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    for admin_user in pagination.items:
        admin_user.municipality = admin_municipality
        admin_user.activity_count = AdminActivityLog.query.filter_by(admin_id=admin_user.id).count()
        admin_user.last_activity_log = AdminActivityLog.query.filter_by(admin_id=admin_user.id).order_by(
            AdminActivityLog.created_at.desc()
        ).first()

    recent_activities = AdminActivityLog.query.join(
        User, User.id == AdminActivityLog.admin_id
    ).join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        User.role == 'admin',
        AdminUsers.municipality == admin_municipality,
    ).order_by(
        AdminActivityLog.created_at.desc()
    ).limit(20).all()

    return render_template(
        'admin/admins.html',
        admins=pagination.items,
        pagination=pagination,
        recent_activities=recent_activities,
        municipality_scope=admin_municipality,
        user=current_user,
    )
