from flask import jsonify, request, render_template
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


@admin_bp.route('/notifications-list')
@login_required
@role_required('admin')
def view_notifications():
    """Display all notifications for the current admin with pagination and filtering"""
    page = request.args.get('page', 1, type=int)
    per_page = 15
    status_filter = request.args.get('status', 'all')  # 'all', 'unread', 'read'
    
    # Base query
    query = Notifications.query.filter_by(user_id=current_user.id)
    
    # Apply status filter
    if status_filter == 'unread':
        query = query.filter_by(is_read=False)
    elif status_filter == 'read':
        query = query.filter_by(is_read=True)
    
    # Order by newest first
    query = query.order_by(desc(Notifications.created_at))
    
    # Paginate
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    notifications = paginated.items
    
    # Add icons and styles to notifications
    for notification in notifications:
        notification.icon = _get_icon(notification.notif_title)
        notification.icon_type = _get_icon_type(notification.notif_title)
    
    # Get statistics
    total_count = Notifications.query.filter_by(user_id=current_user.id).count()
    unread_count = Notifications.query.filter_by(user_id=current_user.id, is_read=False).count()
    
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
        Notifications.query.filter_by(
            user_id=current_user.id,
            is_read=True
        ).delete()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Read notifications deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
