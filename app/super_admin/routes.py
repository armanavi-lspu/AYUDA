from datetime import datetime, timedelta
import secrets
import string

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, desc, func, literal, or_
from werkzeug.security import check_password_hash, generate_password_hash

from app.activity_logger import log_user_modification
from app.extensions import db
from app.location_options import get_municipalities
from app.models import AdminActivityLog, AdminUsers, Announcements, Applications, CommunityUsers, Municipality, Notifications, Programs, User, UserActivityLog
from app.super_admin import super_admin_bp
from app.utils import role_required


def _get_icon(title):
    """Get FontAwesome icon class based on notification title."""
    title_lower = (title or '').lower()
    if 'application' in title_lower or 'applied' in title_lower:
        return 'fa-file-alt'
    if 'approved' in title_lower:
        return 'fa-check-circle'
    if 'rejected' in title_lower or 'denied' in title_lower:
        return 'fa-times-circle'
    if 'document' in title_lower or 'upload' in title_lower:
        return 'fa-cloud-upload-alt'
    if 'assessment' in title_lower or 'schedule' in title_lower:
        return 'fa-clipboard-check'
    if 'announcement' in title_lower:
        return 'fa-bullhorn'
    if 'subsidy' in title_lower:
        return 'fa-money-check-alt'
    if 'welcome' in title_lower:
        return 'fa-hand-sparkles'
    if 'password' in title_lower:
        return 'fa-key'
    return 'fa-info-circle'


def _get_icon_type(title):
    """Get visual icon type based on notification title."""
    title_lower = (title or '').lower()
    if 'approved' in title_lower:
        return 'success'
    if 'rejected' in title_lower or 'denied' in title_lower:
        return 'danger'
    if 'reminder' in title_lower or 'warning' in title_lower:
        return 'warning'
    if 'document' in title_lower or 'upload' in title_lower:
        return 'info'
    if 'application' in title_lower or 'applied' in title_lower:
        return 'primary'
    return 'info'


def _normalize_municipality_name(value):
    """Normalize municipality text for consistent matching and storage."""
    return ' '.join((value or '').strip().split())


@super_admin_bp.context_processor
def inject_super_admin_notification_nav():
    """Provide lightweight notification context for super admin templates."""
    if current_user.is_authenticated and current_user.role == 'super_admin':
        notifications = Notifications.query.filter_by(
            user_id=current_user.id
        ).order_by(desc(Notifications.created_at)).limit(8).all()

        for notification in notifications:
            notification.icon = _get_icon(notification.notif_title)
            notification.icon_type = _get_icon_type(notification.notif_title)

        unread_count = Notifications.query.filter_by(
            user_id=current_user.id,
            is_read=False,
        ).count()
        return {
            'super_admin_recent_notifications': notifications,
            'super_admin_unread_count': unread_count,
        }

    return {
        'super_admin_recent_notifications': [],
        'super_admin_unread_count': 0,
    }


@super_admin_bp.route('/dashboard')
@login_required
@role_required('super_admin')
def dashboard():
    """Super Admin dashboard with system-wide quick performance overview."""
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    total_super_admins = User.query.filter_by(role='super_admin').count()
    total_admins = User.query.filter_by(role='admin').count()
    total_community = User.query.filter_by(role='community').count()
    total_users = total_super_admins + total_admins + total_community

    active_admins = db.session.query(func.count(func.distinct(User.id))).outerjoin(
        AdminActivityLog, AdminActivityLog.admin_id == User.id
    ).filter(
        User.role == 'admin'
    ).filter(
        or_(
            User.last_activity >= seven_days_ago,
            AdminActivityLog.created_at >= seven_days_ago,
        )
    ).scalar() or 0
    inactive_admins = max(total_admins - active_admins, 0)

    active_community_users = db.session.query(func.count(func.distinct(User.id))).outerjoin(
        UserActivityLog, UserActivityLog.user_id == User.id
    ).filter(
        User.role == 'community'
    ).filter(
        or_(
            User.last_activity >= seven_days_ago,
            UserActivityLog.created_at >= seven_days_ago,
        )
    ).scalar() or 0
    inactive_community_users = max(total_community - active_community_users, 0)

    configured_names = [
        row[0]
        for row in db.session.query(Municipality.name).filter(
            Municipality.name.isnot(None),
            Municipality.name != ''
        ).all()
    ]
    source_names = [
        row[0]
        for row in db.session.query(AdminUsers.municipality).filter(
            AdminUsers.municipality.isnot(None),
            AdminUsers.municipality != ''
        ).all()
    ] + [
        row[0]
        for row in db.session.query(CommunityUsers.municipality).filter(
            CommunityUsers.municipality.isnot(None),
            CommunityUsers.municipality != ''
        ).all()
    ]

    municipality_name_by_key = {}
    for raw_name in get_municipalities() + configured_names + source_names:
        normalized_name = _normalize_municipality_name(raw_name)
        if not normalized_name:
            continue
        municipality_name_by_key.setdefault(normalized_name.lower(), normalized_name)

    total_municipalities = len(municipality_name_by_key)

    active_municipality_keys = set()
    active_admin_municipality_rows = db.session.query(AdminUsers.municipality).join(
        User, User.id == AdminUsers.user_id
    ).outerjoin(
        AdminActivityLog, AdminActivityLog.admin_id == User.id
    ).filter(
        AdminUsers.municipality.isnot(None),
        AdminUsers.municipality != ''
    ).filter(
        or_(
            User.last_activity >= seven_days_ago,
            AdminActivityLog.created_at >= seven_days_ago,
        )
    ).all()
    for (municipality_name,) in active_admin_municipality_rows:
        normalized_name = _normalize_municipality_name(municipality_name)
        if normalized_name:
            active_municipality_keys.add(normalized_name.lower())

    active_community_municipality_rows = db.session.query(CommunityUsers.municipality).join(
        User, User.id == CommunityUsers.user_id
    ).outerjoin(
        UserActivityLog, UserActivityLog.user_id == User.id
    ).filter(
        CommunityUsers.municipality.isnot(None),
        CommunityUsers.municipality != ''
    ).filter(
        or_(
            User.last_activity >= seven_days_ago,
            UserActivityLog.created_at >= seven_days_ago,
        )
    ).all()
    for (municipality_name,) in active_community_municipality_rows:
        normalized_name = _normalize_municipality_name(municipality_name)
        if normalized_name:
            active_municipality_keys.add(normalized_name.lower())

    application_municipality_rows = db.session.query(CommunityUsers.municipality).join(
        Applications, Applications.user_id == CommunityUsers.user_id
    ).filter(
        CommunityUsers.municipality.isnot(None),
        CommunityUsers.municipality != '',
        Applications.application_date >= seven_days_ago,
    ).all()
    for (municipality_name,) in application_municipality_rows:
        normalized_name = _normalize_municipality_name(municipality_name)
        if normalized_name:
            active_municipality_keys.add(normalized_name.lower())

    active_municipalities = len(active_municipality_keys.intersection(municipality_name_by_key.keys()))
    inactive_municipalities = max(total_municipalities - active_municipalities, 0)

    recent_applications_7d = Applications.query.filter(
        Applications.application_date >= seven_days_ago
    ).count()
    total_programs = Programs.query.count()
    active_programs = Programs.query.filter(Programs.is_active.is_(True)).count()
    recent_programs_7d = Programs.query.filter(Programs.date >= seven_days_ago).count()
    total_announcements = Announcements.query.count()
    published_announcements = Announcements.query.filter(
        Announcements.status == 'published'
    ).count()
    recent_announcements_7d = Announcements.query.filter(
        Announcements.created_at >= seven_days_ago
    ).count()

    today = now.date()
    daily_dates = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    day_label_lookup = {day: day.strftime('%b %d') for day in daily_dates}
    weekly_activity_map = {
        day: {'applications': 0, 'programs': 0, 'announcements': 0}
        for day in daily_dates
    }
    weekly_start = datetime.combine(daily_dates[0], datetime.min.time())

    for app in Applications.query.filter(Applications.application_date >= weekly_start).all():
        if app.application_date:
            day = app.application_date.date()
            if day in weekly_activity_map:
                weekly_activity_map[day]['applications'] += 1

    for program in Programs.query.filter(Programs.date >= weekly_start).all():
        if program.date:
            day = program.date.date()
            if day in weekly_activity_map:
                weekly_activity_map[day]['programs'] += 1

    for announcement in Announcements.query.filter(Announcements.created_at >= weekly_start).all():
        if announcement.created_at:
            day = announcement.created_at.date()
            if day in weekly_activity_map:
                weekly_activity_map[day]['announcements'] += 1

    weekly_activity_chart = {
        'labels': [day_label_lookup[day] for day in daily_dates],
        'applications': [weekly_activity_map[day]['applications'] for day in daily_dates],
        'programs': [weekly_activity_map[day]['programs'] for day in daily_dates],
        'announcements': [weekly_activity_map[day]['announcements'] for day in daily_dates],
    }

    municipality_application_totals = {}
    for municipality_name, count in db.session.query(
        CommunityUsers.municipality,
        func.count(Applications.id)
    ).join(
        Applications, Applications.user_id == CommunityUsers.user_id
    ).filter(
        CommunityUsers.municipality.isnot(None),
        CommunityUsers.municipality != ''
    ).group_by(
        CommunityUsers.municipality
    ).all():
        normalized_name = _normalize_municipality_name(municipality_name)
        if not normalized_name:
            continue
        key = normalized_name.lower()
        municipality_application_totals[key] = municipality_application_totals.get(key, 0) + int(count or 0)
        municipality_name_by_key.setdefault(key, normalized_name)

    top_municipality_rows = sorted(
        municipality_application_totals.items(),
        key=lambda row: row[1],
        reverse=True,
    )[:8]
    top_municipality_applications_chart = {
        'labels': [municipality_name_by_key.get(key, key.title()) for key, _ in top_municipality_rows],
        'data': [count for _, count in top_municipality_rows],
    }

    municipality_status_chart = {
        'labels': ['Active', 'Inactive'],
        'data': [active_municipalities, inactive_municipalities],
    }
    account_status_chart = {
        'labels': ['Admins', 'Community Users'],
        'active': [active_admins, active_community_users],
        'inactive': [inactive_admins, inactive_community_users],
    }

    recent_admin_logs = AdminActivityLog.query.order_by(
        AdminActivityLog.created_at.desc()
    ).limit(8).all()
    recent_user_logs = UserActivityLog.query.order_by(
        UserActivityLog.created_at.desc()
    ).limit(8).all()

    return render_template(
        'super_admin/dashboard.html',
        user=current_user,
        total_users=total_users,
        total_super_admins=total_super_admins,
        total_admins=total_admins,
        total_community=total_community,
        total_municipalities=total_municipalities,
        active_municipalities=active_municipalities,
        inactive_municipalities=inactive_municipalities,
        active_admins=active_admins,
        inactive_admins=inactive_admins,
        active_community_users=active_community_users,
        inactive_community_users=inactive_community_users,
        recent_applications_7d=recent_applications_7d,
        total_programs=total_programs,
        active_programs=active_programs,
        recent_programs_7d=recent_programs_7d,
        total_announcements=total_announcements,
        published_announcements=published_announcements,
        recent_announcements_7d=recent_announcements_7d,
        municipality_status_chart=municipality_status_chart,
        account_status_chart=account_status_chart,
        weekly_activity_chart=weekly_activity_chart,
        top_municipality_applications_chart=top_municipality_applications_chart,
        recent_admin_logs=recent_admin_logs,
        recent_user_logs=recent_user_logs,
    )


@super_admin_bp.route('/accounts')
@login_required
@role_required('super_admin')
def accounts():
    """Community user account controls for super admin."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search = (request.args.get('search') or '').strip()
    municipality_filter = (request.args.get('municipality') or '').strip()

    query = User.query.join(
        CommunityUsers, CommunityUsers.user_id == User.id
    ).filter(
        User.role == 'community'
    )

    if search:
        term = f'%{search}%'
        query = query.filter(
            or_(
                User.first_name.ilike(term),
                User.last_name.ilike(term),
                User.email.ilike(term),
                (User.first_name + ' ' + User.last_name).ilike(term),
                CommunityUsers.municipality.ilike(term),
                CommunityUsers.barangay.ilike(term),
            )
        )

    if municipality_filter:
        query = query.filter(CommunityUsers.municipality == municipality_filter)

    pagination = query.order_by(desc(User.created_at)).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    users = pagination.items
    for user in users:
        user.application_count = Applications.query.filter_by(user_id=user.id).count()

    municipalities = sorted(
        {
            m
            for m in (
                [name for name in get_municipalities()] +
                [row[0] for row in db.session.query(CommunityUsers.municipality).filter(CommunityUsers.municipality.isnot(None)).all()]
            )
            if m
        }
    )

    total_users = User.query.filter_by(role='community').count()
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    active_users = User.query.filter(
        User.role == 'community',
        User.last_activity >= seven_days_ago,
    ).count()
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = User.query.filter(
        User.role == 'community',
        User.created_at >= start_of_month,
    ).count()

    return render_template(
        'super_admin/accounts.html',
        user=current_user,
        users=users,
        pagination=pagination,
        municipalities=municipalities,
        total_users=total_users,
        active_users=active_users,
        new_this_month=new_this_month,
    )


@super_admin_bp.route('/accounts/community/reset-password/<int:user_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def reset_community_user_password(user_id):
    """Reset a community user's password and notify them with a temporary code."""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()

    reset_code = ''.join(secrets.choice(string.digits) for _ in range(8))
    community_user.password_hash = generate_password_hash(reset_code, method='pbkdf2:sha256')

    try:
        notification = Notifications(
            user_id=user_id,
            notif_title='Password Reset',
            notif_message=(
                f'Your password has been reset by a super administrator. '
                f'Your temporary password/reset code is: {reset_code}. '
                f'Use this code to log in. It is strongly recommended that you change your password immediately.'
            ),
            related_type='profile',
            related_id=user_id,
            created_at=datetime.utcnow(),
        )
        db.session.add(notification)

        log_user_modification(community_user, 'reset_password', {
            'reset_code_delivery': 'notification_and_flash',
            'reset_code_length': len(reset_code),
            'managed_by': 'super_admin',
        })

        db.session.commit()

        flash(
            f'Password reset successfully for {community_user.first_name} {community_user.last_name}. '
            f'New temporary password/reset code: {reset_code}',
            'success',
        )
    except Exception as e:
        db.session.rollback()
        flash(f'Error resetting password: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('super_admin.accounts'))


@super_admin_bp.route('/accounts/community/toggle-status/<int:user_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def toggle_community_user_status(user_id):
    """Notify community user about account restriction/restore."""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()
    action = (request.form.get('action') or 'disable').strip().lower()

    if action not in {'disable', 'enable'}:
        flash('Invalid account action.', 'danger')
        return redirect(request.referrer or url_for('super_admin.accounts'))

    try:
        if action == 'disable':
            notification = Notifications(
                user_id=user_id,
                notif_title='Account Restricted',
                notif_message='Your account has been restricted by a super administrator. Please contact support for more information.',
                related_type='profile',
                created_at=datetime.utcnow(),
            )
            db.session.add(notification)
            log_user_modification(community_user, 'suspend', {'managed_by': 'super_admin'})
            flash(f'Account restricted for {community_user.first_name} {community_user.last_name}.', 'warning')
        else:
            notification = Notifications(
                user_id=user_id,
                notif_title='Account Restored',
                notif_message='Your account has been restored by a super administrator. You can now access all features.',
                related_type='profile',
                created_at=datetime.utcnow(),
            )
            db.session.add(notification)
            log_user_modification(community_user, 'unsuspend', {'managed_by': 'super_admin'})
            flash(f'Account restored for {community_user.first_name} {community_user.last_name}.', 'success')

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating account status: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('super_admin.accounts'))


@super_admin_bp.route('/accounts/community/delete/<int:user_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_community_user_account(user_id):
    """Delete a community user account if it has no linked applications."""
    community_user = User.query.filter_by(id=user_id, role='community').first_or_404()
    app_count = Applications.query.filter_by(user_id=user_id).count()
    if app_count > 0:
        flash(
            f'Cannot delete user {community_user.first_name} {community_user.last_name} because they have {app_count} application(s).',
            'danger',
        )
        return redirect(request.referrer or url_for('super_admin.accounts'))

    try:
        user_name = f'{community_user.first_name} {community_user.last_name}'

        if community_user.community_profile:
            db.session.delete(community_user.community_profile)

        Notifications.query.filter_by(user_id=user_id).delete()
        UserActivityLog.query.filter_by(user_id=user_id).delete()

        log_user_modification(community_user, 'delete', {'managed_by': 'super_admin'})
        db.session.delete(community_user)
        db.session.commit()

        flash(f'User {user_name} deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('super_admin.accounts'))


@super_admin_bp.route('/municipalities')
@login_required
@role_required('super_admin')
def municipalities():
    """Municipality controls page with CRUD and usage insights."""
    search = _normalize_municipality_name(request.args.get('search') or '')

    configured_municipalities = Municipality.query.order_by(Municipality.name.asc()).all()
    configured_by_key = {
        municipality.name.lower(): municipality
        for municipality in configured_municipalities
        if municipality.name
    }

    name_by_key = {
        name.lower(): name
        for name in get_municipalities()
        if name
    }

    admin_counts = {}
    for municipality, count in db.session.query(
        AdminUsers.municipality,
        func.count(AdminUsers.id)
    ).filter(
        AdminUsers.municipality.isnot(None),
        AdminUsers.municipality != ''
    ).group_by(AdminUsers.municipality).all():
        normalized_name = _normalize_municipality_name(municipality)
        if not normalized_name:
            continue
        key = normalized_name.lower()
        admin_counts[key] = admin_counts.get(key, 0) + int(count or 0)
        name_by_key.setdefault(key, normalized_name)

    community_counts = {}
    for municipality, count in db.session.query(
        CommunityUsers.municipality,
        func.count(CommunityUsers.id)
    ).filter(
        CommunityUsers.municipality.isnot(None),
        CommunityUsers.municipality != ''
    ).group_by(CommunityUsers.municipality).all():
        normalized_name = _normalize_municipality_name(municipality)
        if not normalized_name:
            continue
        key = normalized_name.lower()
        community_counts[key] = community_counts.get(key, 0) + int(count or 0)
        name_by_key.setdefault(key, normalized_name)

    application_counts = {}
    for municipality, count in db.session.query(
        CommunityUsers.municipality,
        func.count(Applications.id)
    ).join(
        Applications, Applications.user_id == CommunityUsers.user_id
    ).filter(
        CommunityUsers.municipality.isnot(None),
        CommunityUsers.municipality != ''
    ).group_by(CommunityUsers.municipality).all():
        normalized_name = _normalize_municipality_name(municipality)
        if not normalized_name:
            continue
        key = normalized_name.lower()
        application_counts[key] = application_counts.get(key, 0) + int(count or 0)
        name_by_key.setdefault(key, normalized_name)

    program_counts = {}
    for municipality, count in db.session.query(
        CommunityUsers.municipality,
        func.count(func.distinct(Applications.program_id))
    ).join(
        Applications, Applications.user_id == CommunityUsers.user_id
    ).filter(
        CommunityUsers.municipality.isnot(None),
        CommunityUsers.municipality != ''
    ).group_by(CommunityUsers.municipality).all():
        normalized_name = _normalize_municipality_name(municipality)
        if not normalized_name:
            continue
        key = normalized_name.lower()
        program_counts[key] = program_counts.get(key, 0) + int(count or 0)
        name_by_key.setdefault(key, normalized_name)

    rows = []
    for key, display_name in name_by_key.items():
        if search and search.lower() not in display_name.lower():
            continue

        configured_record = configured_by_key.get(key)
        admin_count = int(admin_counts.get(key, 0))
        community_count = int(community_counts.get(key, 0))

        rows.append({
            'id': configured_record.id if configured_record else None,
            'name': configured_record.name if configured_record else display_name,
            'admin_count': admin_count,
            'community_count': community_count,
            'total_accounts': admin_count + community_count,
            'application_count': int(application_counts.get(key, 0)),
            'program_count': int(program_counts.get(key, 0)),
            'is_configured': bool(configured_record),
            'updated_at': configured_record.updated_at if configured_record else None,
        })

    rows.sort(
        key=lambda item: (
            -item['total_accounts'],
            -item['application_count'],
            item['name'].lower(),
        )
    )

    total_accounts = sum(item['total_accounts'] for item in rows)
    configured_count = sum(1 for item in rows if item['is_configured'])
    observed_count = len(rows) - configured_count

    return render_template(
        'super_admin/municipalities.html',
        user=current_user,
        municipalities=rows,
        configured_count=configured_count,
        observed_count=observed_count,
        total_accounts=total_accounts,
        search=search,
    )


@super_admin_bp.route('/municipalities/add', methods=['POST'])
@login_required
@role_required('super_admin')
def add_municipality():
    """Create a municipality record in the centralized registry."""
    municipality_name = _normalize_municipality_name(request.form.get('name') or '')
    if not municipality_name:
        flash('Municipality name is required.', 'danger')
        return redirect(request.referrer or url_for('super_admin.municipalities'))

    existing = Municipality.query.filter(
        func.lower(Municipality.name) == municipality_name.lower()
    ).first()
    if existing:
        flash(f'{existing.name} is already configured.', 'warning')
        return redirect(request.referrer or url_for('super_admin.municipalities'))

    try:
        db.session.add(Municipality(name=municipality_name))
        db.session.commit()
        flash(f'{municipality_name} was added to municipality controls.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Unable to add municipality: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('super_admin.municipalities'))


@super_admin_bp.route('/municipalities/<int:municipality_id>/edit', methods=['POST'])
@login_required
@role_required('super_admin')
def edit_municipality(municipality_id):
    """Rename a municipality and sync related profile records."""
    municipality = Municipality.query.get_or_404(municipality_id)
    new_name = _normalize_municipality_name(request.form.get('name') or '')

    if not new_name:
        flash('Municipality name is required.', 'danger')
        return redirect(request.referrer or url_for('super_admin.municipalities'))

    duplicate = Municipality.query.filter(
        func.lower(Municipality.name) == new_name.lower(),
        Municipality.id != municipality.id,
    ).first()
    if duplicate:
        flash(f'{duplicate.name} already exists.', 'warning')
        return redirect(request.referrer or url_for('super_admin.municipalities'))

    old_name = municipality.name
    try:
        municipality.name = new_name

        admin_updates = 0
        community_updates = 0
        if old_name and old_name.lower() != new_name.lower():
            admin_updates = AdminUsers.query.filter(
                func.lower(AdminUsers.municipality) == old_name.lower()
            ).update({AdminUsers.municipality: new_name}, synchronize_session=False)

            community_updates = CommunityUsers.query.filter(
                func.lower(CommunityUsers.municipality) == old_name.lower()
            ).update({CommunityUsers.municipality: new_name}, synchronize_session=False)

        db.session.commit()
        flash(
            f'Municipality updated to {new_name}. '
            f'Synced {admin_updates} admin profile(s) and {community_updates} community profile(s).',
            'success',
        )
    except Exception as e:
        db.session.rollback()
        flash(f'Unable to update municipality: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('super_admin.municipalities'))


@super_admin_bp.route('/municipalities/<int:municipality_id>/delete', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_municipality(municipality_id):
    """Delete a municipality if it is not used by any account profile."""
    municipality = Municipality.query.get_or_404(municipality_id)
    normalized_name = municipality.name.lower()

    admin_usage = AdminUsers.query.filter(
        func.lower(AdminUsers.municipality) == normalized_name
    ).count()
    community_usage = CommunityUsers.query.filter(
        func.lower(CommunityUsers.municipality) == normalized_name
    ).count()

    if admin_usage or community_usage:
        flash(
            f'Cannot delete {municipality.name}. '
            f'It is used by {admin_usage} admin profile(s) and {community_usage} community profile(s).',
            'danger',
        )
        return redirect(request.referrer or url_for('super_admin.municipalities'))

    try:
        deleted_name = municipality.name
        db.session.delete(municipality)
        db.session.commit()
        flash(f'{deleted_name} was removed from municipality controls.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Unable to delete municipality: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('super_admin.municipalities'))


@super_admin_bp.route('/municipalities/view/<path:municipality_name>')
@login_required
@role_required('super_admin')
def municipality_detail(municipality_name):
    """Municipality performance page with account, application, and program analytics."""
    normalized_name = _normalize_municipality_name(municipality_name)
    if not normalized_name:
        flash('Municipality was not found.', 'danger')
        return redirect(url_for('super_admin.municipalities'))

    registry_entry = Municipality.query.filter(
        func.lower(Municipality.name) == normalized_name.lower()
    ).first()
    display_name = registry_entry.name if registry_entry else normalized_name
    municipality_key = display_name.lower()
    active_tab = (request.args.get('tab') or 'overview').strip().lower()
    if active_tab not in {'overview', 'users', 'admins'}:
        active_tab = 'overview'

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    total_admins = AdminUsers.query.filter(
        func.lower(AdminUsers.municipality) == municipality_key
    ).count()
    total_community_users = CommunityUsers.query.filter(
        func.lower(CommunityUsers.municipality) == municipality_key
    ).count()

    active_admins = User.query.join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        func.lower(AdminUsers.municipality) == municipality_key,
        User.last_activity >= seven_days_ago,
    ).count()
    active_community_users = User.query.join(
        CommunityUsers, CommunityUsers.user_id == User.id
    ).filter(
        func.lower(CommunityUsers.municipality) == municipality_key,
        User.last_activity >= seven_days_ago,
    ).count()

    applications_query = Applications.query.join(
        CommunityUsers, CommunityUsers.user_id == Applications.user_id
    ).filter(
        func.lower(CommunityUsers.municipality) == municipality_key
    )

    total_applications = applications_query.count()
    recent_applications = applications_query.filter(
        Applications.application_date >= thirty_days_ago
    ).count()

    status_counts = {
        status: int(count or 0)
        for status, count in db.session.query(
            Applications.application_status,
            func.count(Applications.id)
        ).join(
            CommunityUsers, CommunityUsers.user_id == Applications.user_id
        ).filter(
            func.lower(CommunityUsers.municipality) == municipality_key
        ).group_by(
            Applications.application_status
        ).all()
        if status
    }

    pending_count = int(status_counts.get('pending', 0))
    approved_count = int(status_counts.get('approved', 0))
    active_count = int(status_counts.get('active', 0))
    completed_count = int(status_counts.get('completed', 0))
    rejected_count = int(status_counts.get('rejected', 0))

    approved_pipeline = approved_count + active_count + completed_count
    approval_rate = round((approved_pipeline / total_applications) * 100, 1) if total_applications else 0.0
    completion_rate = round((completed_count / total_applications) * 100, 1) if total_applications else 0.0

    total_programs = db.session.query(
        func.count(func.distinct(Applications.program_id))
    ).join(
        CommunityUsers, CommunityUsers.user_id == Applications.user_id
    ).filter(
        func.lower(CommunityUsers.municipality) == municipality_key
    ).scalar() or 0

    application_count_label = func.count(Applications.id).label('application_count')
    accepted_count_label = func.sum(
        case(
            (Applications.application_status.in_(['approved', 'active', 'completed']), 1),
            else_=0,
        )
    ).label('accepted_count')

    top_program_rows = db.session.query(
        Programs.id.label('program_id'),
        Programs.program_name.label('program_name'),
        application_count_label,
        accepted_count_label,
    ).join(
        Applications, Applications.program_id == Programs.id
    ).join(
        CommunityUsers, CommunityUsers.user_id == Applications.user_id
    ).filter(
        func.lower(CommunityUsers.municipality) == municipality_key
    ).group_by(
        Programs.id,
        Programs.program_name,
    ).order_by(
        application_count_label.desc(),
        Programs.program_name.asc(),
    ).limit(8).all()

    top_programs = []
    for row in top_program_rows:
        accepted_count = int(row.accepted_count or 0)
        application_count = int(row.application_count or 0)
        top_programs.append({
            'program_id': row.program_id,
            'program_name': row.program_name,
            'application_count': application_count,
            'accepted_count': accepted_count,
            'acceptance_rate': round((accepted_count / application_count) * 100, 1) if application_count else 0.0,
        })

    top_barangays = db.session.query(
        CommunityUsers.barangay,
        func.count(CommunityUsers.id).label('resident_count'),
    ).filter(
        func.lower(CommunityUsers.municipality) == municipality_key,
        CommunityUsers.barangay.isnot(None),
        CommunityUsers.barangay != '',
    ).group_by(
        CommunityUsers.barangay
    ).order_by(
        desc('resident_count'),
        CommunityUsers.barangay.asc(),
    ).limit(8).all()

    admin_users = User.query.join(
        AdminUsers, AdminUsers.user_id == User.id
    ).filter(
        func.lower(AdminUsers.municipality) == municipality_key
    ).order_by(
        User.last_name.asc(),
        User.first_name.asc(),
    ).all()

    community_users = User.query.join(
        CommunityUsers, CommunityUsers.user_id == User.id
    ).filter(
        func.lower(CommunityUsers.municipality) == municipality_key
    ).order_by(
        desc(User.last_activity),
        User.last_name.asc(),
    ).all()

    recent_admin_logs = AdminActivityLog.query.join(
        AdminUsers, AdminUsers.user_id == AdminActivityLog.admin_id
    ).join(
        User, User.id == AdminActivityLog.admin_id
    ).filter(
        func.lower(AdminUsers.municipality) == municipality_key
    ).order_by(
        desc(AdminActivityLog.created_at)
    ).limit(8).all()

    recent_user_logs = UserActivityLog.query.join(
        CommunityUsers, CommunityUsers.user_id == UserActivityLog.user_id
    ).join(
        User, User.id == UserActivityLog.user_id
    ).filter(
        func.lower(CommunityUsers.municipality) == municipality_key
    ).order_by(
        desc(UserActivityLog.created_at)
    ).limit(8).all()

    return render_template(
        'super_admin/municipality_detail.html',
        user=current_user,
        municipality_name=display_name,
        active_tab=active_tab,
        registry_entry=registry_entry,
        total_admins=total_admins,
        total_community_users=total_community_users,
        active_admins=active_admins,
        active_community_users=active_community_users,
        total_applications=total_applications,
        recent_applications=recent_applications,
        pending_count=pending_count,
        approved_count=approved_count,
        active_count=active_count,
        completed_count=completed_count,
        rejected_count=rejected_count,
        approval_rate=approval_rate,
        completion_rate=completion_rate,
        total_programs=total_programs,
        top_programs=top_programs,
        top_barangays=top_barangays,
        admin_users=admin_users,
        community_users=community_users,
        recent_admin_logs=recent_admin_logs,
        recent_user_logs=recent_user_logs,
    )


@super_admin_bp.route('/logs/admin')
@login_required
@role_required('super_admin')
def admin_logs():
    """Super admin view for all admin activity logs."""
    page = request.args.get('page', 1, type=int)
    per_page = 30
    search = (request.args.get('search') or '').strip()
    action_filter = (request.args.get('action') or '').strip()
    role_filter = (request.args.get('role') or '').strip().lower()
    sort_order = (request.args.get('sort') or 'newest').strip().lower()

    query = AdminActivityLog.query.join(User, User.id == AdminActivityLog.admin_id)

    if action_filter:
        query = query.filter(AdminActivityLog.action == action_filter)

    if role_filter:
        query = query.filter(User.role == role_filter)

    if search:
        term = f'%{search}%'
        query = query.filter(
            or_(
                AdminActivityLog.description.ilike(term),
                AdminActivityLog.action.ilike(term),
                AdminActivityLog.entity_type.ilike(term),
                User.first_name.ilike(term),
                User.last_name.ilike(term),
                (User.first_name + ' ' + User.last_name).ilike(term),
            )
        )

    action_options = [
        row[0]
        for row in db.session.query(AdminActivityLog.action)
        .filter(AdminActivityLog.action.isnot(None))
        .distinct()
        .order_by(AdminActivityLog.action)
        .all()
    ]
    role_options = [
        row[0]
        for row in db.session.query(User.role)
        .join(AdminActivityLog, AdminActivityLog.admin_id == User.id)
        .filter(User.role.isnot(None))
        .distinct()
        .order_by(User.role)
        .all()
    ]

    order_clause = AdminActivityLog.created_at.asc() if sort_order == 'oldest' else AdminActivityLog.created_at.desc()

    pagination = query.order_by(order_clause).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    return render_template(
        'super_admin/admin_logs.html',
        user=current_user,
        activities=pagination.items,
        pagination=pagination,
        action_options=action_options,
        role_options=role_options,
        selected_action=action_filter,
        selected_role=role_filter,
        selected_sort=sort_order,
    )


@super_admin_bp.route('/logs/users')
@login_required
@role_required('super_admin')
def user_logs():
    """Super admin view for all community user activity logs."""
    page = request.args.get('page', 1, type=int)
    per_page = 30
    search = (request.args.get('search') or '').strip()
    action_filter = (request.args.get('action') or '').strip()
    role_filter = (request.args.get('role') or '').strip().lower()
    sort_order = (request.args.get('sort') or 'newest').strip().lower()

    query = UserActivityLog.query.join(User, User.id == UserActivityLog.user_id)

    if action_filter:
        query = query.filter(UserActivityLog.action == action_filter)

    if role_filter:
        query = query.filter(User.role == role_filter)

    if search:
        term = f'%{search}%'
        query = query.filter(
            or_(
                UserActivityLog.description.ilike(term),
                UserActivityLog.action.ilike(term),
                UserActivityLog.entity_type.ilike(term),
                User.first_name.ilike(term),
                User.last_name.ilike(term),
                (User.first_name + ' ' + User.last_name).ilike(term),
            )
        )

    action_options = [
        row[0]
        for row in db.session.query(UserActivityLog.action)
        .filter(UserActivityLog.action.isnot(None))
        .distinct()
        .order_by(UserActivityLog.action)
        .all()
    ]
    role_options = [
        row[0]
        for row in db.session.query(User.role)
        .join(UserActivityLog, UserActivityLog.user_id == User.id)
        .filter(User.role.isnot(None))
        .distinct()
        .order_by(User.role)
        .all()
    ]

    order_clause = UserActivityLog.created_at.asc() if sort_order == 'oldest' else UserActivityLog.created_at.desc()

    pagination = query.order_by(order_clause).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    return render_template(
        'super_admin/user_logs.html',
        user=current_user,
        activities=pagination.items,
        pagination=pagination,
        action_options=action_options,
        role_options=role_options,
        selected_action=action_filter,
        selected_role=role_filter,
        selected_sort=sort_order,
    )


@super_admin_bp.route('/logs/system')
@login_required
@role_required('super_admin')
def system_logs():
    """Unified, unfiltered system logs including super-admin/admin/user activities."""
    page = request.args.get('page', 1, type=int)
    per_page = 40
    search = (request.args.get('search') or '').strip()
    action_filter = (request.args.get('action') or '').strip()
    role_filter = (request.args.get('role') or '').strip().lower()
    sort_order = (request.args.get('sort') or 'newest').strip().lower()

    admin_logs_query = db.session.query(
        AdminActivityLog.id.label('log_id'),
        AdminActivityLog.created_at.label('created_at'),
        User.first_name.label('first_name'),
        User.last_name.label('last_name'),
        User.role.label('actor_role'),
        AdminActivityLog.action.label('action'),
        AdminActivityLog.action_type.label('action_type'),
        AdminActivityLog.entity_type.label('entity_type'),
        AdminActivityLog.description.label('description'),
        literal('admin_activity').label('source'),
    ).join(User, User.id == AdminActivityLog.admin_id)

    user_logs_query = db.session.query(
        UserActivityLog.id.label('log_id'),
        UserActivityLog.created_at.label('created_at'),
        User.first_name.label('first_name'),
        User.last_name.label('last_name'),
        User.role.label('actor_role'),
        UserActivityLog.action.label('action'),
        UserActivityLog.action_type.label('action_type'),
        UserActivityLog.entity_type.label('entity_type'),
        UserActivityLog.description.label('description'),
        literal('user_activity').label('source'),
    ).join(User, User.id == UserActivityLog.user_id)

    combined_logs = admin_logs_query.union_all(user_logs_query).subquery()

    filtered_query = db.session.query(combined_logs)
    if action_filter:
        filtered_query = filtered_query.filter(combined_logs.c.action == action_filter)
    if role_filter:
        filtered_query = filtered_query.filter(combined_logs.c.actor_role == role_filter)
    if search:
        term = f'%{search}%'
        filtered_query = filtered_query.filter(
            or_(
                combined_logs.c.description.ilike(term),
                combined_logs.c.action.ilike(term),
                combined_logs.c.entity_type.ilike(term),
                combined_logs.c.first_name.ilike(term),
                combined_logs.c.last_name.ilike(term),
            )
        )

    action_options = [
        row[0]
        for row in db.session.query(combined_logs.c.action)
        .filter(combined_logs.c.action.isnot(None))
        .distinct()
        .order_by(combined_logs.c.action)
        .all()
    ]
    role_options = [
        row[0]
        for row in db.session.query(combined_logs.c.actor_role)
        .filter(combined_logs.c.actor_role.isnot(None))
        .distinct()
        .order_by(combined_logs.c.actor_role)
        .all()
    ]

    total_logs = filtered_query.count()
    if page < 1:
        page = 1

    total_pages = max((total_logs + per_page - 1) // per_page, 1)
    if total_logs > 0 and page > total_pages:
        page = total_pages

    order_clause = combined_logs.c.created_at.asc() if sort_order == 'oldest' else combined_logs.c.created_at.desc()

    logs = filtered_query.order_by(order_clause).offset((page - 1) * per_page).limit(per_page).all()

    return render_template(
        'super_admin/system_logs.html',
        user=current_user,
        logs=logs,
        page=page,
        per_page=per_page,
        total_logs=total_logs,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        action_options=action_options,
        role_options=role_options,
        selected_action=action_filter,
        selected_role=role_filter,
        selected_sort=sort_order,
    )


@super_admin_bp.route('/notifications')
@login_required
@role_required('super_admin')
def notifications():
    """Super admin notifications list view with status filters."""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    status_filter = (request.args.get('status') or 'all').strip().lower()

    query = Notifications.query.filter_by(user_id=current_user.id)
    if status_filter == 'unread':
        query = query.filter_by(is_read=False)
    elif status_filter == 'read':
        query = query.filter_by(is_read=True)

    paginated = query.order_by(desc(Notifications.created_at)).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    for notification in paginated.items:
        notification.icon = _get_icon(notification.notif_title)
        notification.icon_type = _get_icon_type(notification.notif_title)

    total_count = Notifications.query.filter_by(user_id=current_user.id).count()
    unread_count = Notifications.query.filter_by(
        user_id=current_user.id,
        is_read=False,
    ).count()

    return render_template(
        'super_admin/notifications.html',
        user=current_user,
        notifications=paginated.items,
        paginated=paginated,
        total_count=total_count,
        unread_count=unread_count,
        status_filter=status_filter,
    )


@super_admin_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
@role_required('super_admin')
def mark_notification_read(notification_id):
    """Mark a single super admin notification as read."""
    notification = Notifications.query.filter_by(
        id=notification_id,
        user_id=current_user.id,
    ).first()

    if not notification:
        flash('Notification not found.', 'danger')
        return redirect(request.referrer or url_for('super_admin.notifications'))

    if not notification.is_read:
        notification.is_read = True
        db.session.commit()
        flash('Notification marked as read.', 'success')

    return redirect(request.referrer or url_for('super_admin.notifications'))


@super_admin_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
@role_required('super_admin')
def mark_all_notifications_read():
    """Mark all super admin notifications as read."""
    Notifications.query.filter_by(
        user_id=current_user.id,
        is_read=False,
    ).update({'is_read': True})
    db.session.commit()

    flash('All notifications marked as read.', 'success')
    return redirect(request.referrer or url_for('super_admin.notifications'))


@super_admin_bp.route('/profile')
@login_required
@role_required('super_admin')
def profile():
    """Super admin profile page."""
    return render_template('super_admin/profile.html', user=current_user)


@super_admin_bp.route('/profile/update', methods=['POST'])
@login_required
@role_required('super_admin')
def update_profile():
    """Update super admin name fields."""
    first_name = (request.form.get('first_name') or '').strip()
    middle_name = (request.form.get('middle_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()

    if not first_name or not last_name:
        flash('First name and last name are required.', 'danger')
        return redirect(url_for('super_admin.profile'))

    current_user.first_name = first_name
    current_user.middle_name = middle_name
    current_user.last_name = last_name
    db.session.commit()

    flash('Profile updated successfully.', 'success')
    return redirect(url_for('super_admin.profile'))


@super_admin_bp.route('/settings')
@login_required
@role_required('super_admin')
def settings():
    """Super admin settings page."""
    return render_template('super_admin/settings.html', user=current_user)


@super_admin_bp.route('/settings/change-password', methods=['POST'])
@login_required
@role_required('super_admin')
def change_password():
    """Change super admin account password."""
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not check_password_hash(current_user.password_hash, current_password):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('super_admin.settings'))

    if len(new_password) < 8:
        flash('New password must be at least 8 characters.', 'danger')
        return redirect(url_for('super_admin.settings'))

    if new_password != confirm_password:
        flash('New password and confirmation do not match.', 'danger')
        return redirect(url_for('super_admin.settings'))

    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    flash('Password changed successfully.', 'success')
    return redirect(url_for('super_admin.settings'))
