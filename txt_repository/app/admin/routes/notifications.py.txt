from datetime import datetime, timedelta
import math

from flask import jsonify, request, render_template
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required, manila_strftime
from app.models import Notifications, Applications, Assessment, CommunityUsers, UserActivityLog
from app.extensions import db
from sqlalchemy import desc, func


READ_NOTIFICATION_RETENTION_DAYS = 120
ADMIN_ALERT_RETENTION_DAYS = 60
MAX_NOTIFICATION_SCAN = 1000


class SimplePagination:
    """Lightweight pagination object compatible with template usage."""

    def __init__(self, page, per_page, total):
        self.page = max(1, int(page or 1))
        self.per_page = max(1, int(per_page or 1))
        self.total = max(0, int(total or 0))
        self.pages = max(1, int(math.ceil(self.total / float(self.per_page))))
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1 if self.has_prev else None
        self.next_num = self.page + 1 if self.has_next else None

    def iter_pages(self, left_edge=2, left_current=2, right_current=2, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def _current_admin_municipality_key():
    profile = getattr(current_user, 'admin_profile', None)
    municipality = (profile.municipality or '').strip().lower() if profile else ''
    return municipality or None


def _is_application_in_scope(application_id, municipality_key, cache):
    if application_id in cache:
        return cache[application_id]

    cache[application_id] = db.session.query(Applications.id).join(
        CommunityUsers, Applications.user_id == CommunityUsers.user_id
    ).filter(
        Applications.id == application_id,
        func.lower(func.trim(CommunityUsers.municipality)) == municipality_key,
    ).first() is not None
    return cache[application_id]


def _is_assessment_in_scope(assessment_id, municipality_key, cache):
    if assessment_id in cache:
        return cache[assessment_id]

    cache[assessment_id] = db.session.query(Assessment.id).join(
        Applications, Assessment.application_id == Applications.id
    ).join(
        CommunityUsers, Applications.user_id == CommunityUsers.user_id
    ).filter(
        Assessment.id == assessment_id,
        func.lower(func.trim(CommunityUsers.municipality)) == municipality_key,
    ).first() is not None
    return cache[assessment_id]


def _is_profile_in_scope(profile_user_id, municipality_key, cache):
    if profile_user_id in cache:
        return cache[profile_user_id]

    cache[profile_user_id] = db.session.query(CommunityUsers.id).filter(
        CommunityUsers.user_id == profile_user_id,
        func.lower(func.trim(CommunityUsers.municipality)) == municipality_key,
    ).first() is not None
    return cache[profile_user_id]


def _is_subsidy_in_scope(subsidy_log_id, municipality_key, cache):
    if subsidy_log_id in cache:
        return cache[subsidy_log_id]

    cache[subsidy_log_id] = db.session.query(UserActivityLog.id).join(
        CommunityUsers, UserActivityLog.user_id == CommunityUsers.user_id
    ).filter(
        UserActivityLog.id == subsidy_log_id,
        func.lower(func.trim(CommunityUsers.municipality)) == municipality_key,
    ).first() is not None
    return cache[subsidy_log_id]


def _notification_is_visible(notification, municipality_key, now_utc, caches):
    if not municipality_key:
        return False

    read_cutoff = now_utc - timedelta(days=READ_NOTIFICATION_RETENTION_DAYS)
    if notification.is_read and notification.created_at and notification.created_at < read_cutoff:
        return False

    related_type = (notification.related_type or '').strip().lower()
    related_id = notification.related_id

    if related_type == 'application' and related_id:
        return _is_application_in_scope(related_id, municipality_key, caches['application'])

    if related_type == 'assessment' and related_id:
        return _is_assessment_in_scope(related_id, municipality_key, caches['assessment'])

    if related_type == 'profile' and related_id:
        return _is_profile_in_scope(related_id, municipality_key, caches['profile'])

    if related_type == 'subsidy' and related_id:
        return _is_subsidy_in_scope(related_id, municipality_key, caches['subsidy'])

    if related_type == 'admin_alert':
        cutoff = now_utc - timedelta(days=ADMIN_ALERT_RETENTION_DAYS)
        return bool(notification.created_at and notification.created_at >= cutoff)

    if related_type in {'announcement', 'program'}:
        # Keep direct admin-owned notifications for this user; stale read notifications are already filtered above.
        return True

    if not related_type:
        return not notification.is_read

    return True


def _filtered_notifications(status_filter='all'):
    municipality_key = _current_admin_municipality_key()
    now_utc = datetime.utcnow()

    rows = Notifications.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(Notifications.created_at)).limit(MAX_NOTIFICATION_SCAN).all()

    caches = {
        'application': {},
        'assessment': {},
        'profile': {},
        'subsidy': {},
    }

    filtered = []
    for notif in rows:
        if status_filter == 'unread' and notif.is_read:
            continue
        if status_filter == 'read' and not notif.is_read:
            continue
        if _notification_is_visible(notif, municipality_key, now_utc, caches):
            filtered.append(notif)

    return filtered


@admin_bp.route('/notifications/data')
@login_required
@role_required('admin')
def get_notifications():
    """Return recent notifications for the dropdown"""
    scoped_notifications = _filtered_notifications(status_filter='all')
    notifications = scoped_notifications[:15]
    unread_count = sum(1 for n in scoped_notifications if not n.is_read)

    items = []
    for n in notifications:
        items.append({
            'id': n.id,
            'title': n.notif_title,
            'message': n.notif_message,
            'is_read': n.is_read,
            'url': n.get_admin_url(),
            'created_at': manila_strftime(n.created_at, '%b %d, %Y %I:%M %p', ''),
            'icon': _get_icon(n.notif_title),
            'icon_type': _get_icon_type(n.notif_title),
        })

    return jsonify({
        'success': True,
        'notifications': items,
        'unread_count': unread_count
    })


@admin_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
@role_required('admin')
def mark_notification_read(notification_id):
    """Mark a specific notification as read"""
    notification = Notifications.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first()

    if not notification:
        return jsonify({'success': False, 'message': 'Notification not found'}), 404

    if notification not in _filtered_notifications(status_filter='all'):
        return jsonify({'success': False, 'message': 'Notification is out of municipality scope'}), 403

    if not notification.is_read:
        notification.is_read = True
        db.session.commit()

    return jsonify({'success': True, 'notification_id': notification_id})


@admin_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
@role_required('admin')
def mark_all_notifications_read():
    """Mark all notifications as read for the current admin"""
    scoped_unread_ids = [n.id for n in _filtered_notifications(status_filter='unread')]
    if scoped_unread_ids:
        Notifications.query.filter(
            Notifications.id.in_(scoped_unread_ids)
        ).update({'is_read': True}, synchronize_session=False)

    db.session.commit()

    return jsonify({'success': True})


@admin_bp.route('/notifications/count')
@login_required
@role_required('admin')
def get_notification_count():
    """Return the unread notification count"""
    unread_count = len(_filtered_notifications(status_filter='unread'))

    return jsonify({'success': True, 'unread_count': unread_count})


def _get_icon(title):
    """Get FontAwesome icon class based on notification title"""
    title_lower = title.lower()
    if 'application' in title_lower or 'applied' in title_lower:
        return 'fa-file-alt'
    elif 'approved' in title_lower:
        return 'fa-check-circle'
    elif 'rejected' in title_lower or 'denied' in title_lower:
        return 'fa-times-circle'
    elif 'document' in title_lower or 'upload' in title_lower:
        return 'fa-cloud-upload-alt'
    elif 'assessment' in title_lower or 'schedule' in title_lower:
        return 'fa-clipboard-check'
    elif 'announcement' in title_lower:
        return 'fa-bullhorn'
    elif 'subsidy' in title_lower:
        return 'fa-money-check-alt'
    elif 'welcome' in title_lower:
        return 'fa-hand-sparkles'
    elif 'password' in title_lower:
        return 'fa-key'
    return 'fa-info-circle'


def _get_icon_type(title):
    """Get icon colour type based on notification title"""
    title_lower = title.lower()
    if 'approved' in title_lower:
        return 'success'
    elif 'rejected' in title_lower or 'denied' in title_lower:
        return 'danger'
    elif 'reminder' in title_lower or 'warning' in title_lower:
        return 'warning'
    elif 'document' in title_lower or 'upload' in title_lower:
        return 'info'
    elif 'application' in title_lower or 'applied' in title_lower:
        return 'primary'
    return 'info'


@admin_bp.route('/notifications-list')
@login_required
@role_required('admin')
def view_notifications():
    """Display all notifications for the current admin with pagination and filtering"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    status_filter = request.args.get('status', 'all')  # 'all', 'unread', 'read'

    scoped_notifications = _filtered_notifications(status_filter=status_filter)
    total_filtered = len(scoped_notifications)
    paginated = SimplePagination(page=page, per_page=per_page, total=total_filtered)
    start = (paginated.page - 1) * paginated.per_page
    end = start + paginated.per_page
    notifications = scoped_notifications[start:end]
    
    # Add icons and styles to notifications
    for notification in notifications:
        notification.icon = _get_icon(notification.notif_title)
        notification.icon_type = _get_icon_type(notification.notif_title)
    
    # Get statistics
    all_scoped_notifications = _filtered_notifications(status_filter='all')
    total_count = len(all_scoped_notifications)
    unread_count = sum(1 for n in all_scoped_notifications if not n.is_read)
    
    return render_template('admin/notifications.html',
                         notifications=notifications,
                         paginated=paginated,
                         total_count=total_count,
                         unread_count=unread_count,
                         status_filter=status_filter)


@admin_bp.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_notification(notification_id):
    """Delete a specific notification"""
    notification = Notifications.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first()

    if not notification:
        return jsonify({'success': False, 'message': 'Notification not found'}), 404

    if notification not in _filtered_notifications(status_filter='all'):
        return jsonify({'success': False, 'message': 'Notification is out of municipality scope'}), 403

    try:
        db.session.delete(notification)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Notification deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/notifications/delete-read', methods=['POST'])
@login_required
@role_required('admin')
def delete_read_notifications():
    """Delete all read notifications for the current admin"""
    try:
        scoped_read_ids = [n.id for n in _filtered_notifications(status_filter='read')]
        if scoped_read_ids:
            Notifications.query.filter(Notifications.id.in_(scoped_read_ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Read notifications deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
