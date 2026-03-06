from flask import jsonify, request
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required
from app.models import Notifications
from app.extensions import db
from sqlalchemy import desc


@admin_bp.route('/notifications/data')
@login_required
@role_required('admin')
def get_notifications():
    """Return recent notifications for the dropdown"""
    notifications = Notifications.query.filter_by(
        user_id=current_user.id
    ).order_by(desc(Notifications.created_at)).limit(15).all()

    unread_count = Notifications.query.filter_by(
        user_id=current_user.id, is_read=False
    ).count()

    items = []
    for n in notifications:
        items.append({
            'id': n.id,
            'title': n.notif_title,
            'message': n.notif_message,
            'is_read': n.is_read,
            'url': n.get_admin_url(),
            'created_at': n.created_at.strftime('%b %d, %Y %I:%M %p') if n.created_at else '',
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

    if not notification.is_read:
        notification.is_read = True
        db.session.commit()

    return jsonify({'success': True, 'notification_id': notification_id})


@admin_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
@role_required('admin')
def mark_all_notifications_read():
    """Mark all notifications as read for the current admin"""
    Notifications.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).update({'is_read': True})

    db.session.commit()

    return jsonify({'success': True})


@admin_bp.route('/notifications/count')
@login_required
@role_required('admin')
def get_notification_count():
    """Return the unread notification count"""
    unread_count = Notifications.query.filter_by(
        user_id=current_user.id, is_read=False
    ).count()

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
