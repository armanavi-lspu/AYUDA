from flask import jsonify
from flask_login import login_required, current_user
from app.community import community_bp
from app.utils import role_required
from app.models import Notifications
from app.extensions import db
from sqlalchemy import desc
from datetime import datetime

@community_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
@role_required('community')
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
    
    return jsonify({
        'success': True,
        'notification_id': notification_id
    })

@community_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
@role_required('community')
def mark_all_notifications_read():
    """Mark all notifications as read for the current user"""
    unread_count = Notifications.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).update({'is_read': True})
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'count': unread_count
    })

def cleanup_old_notifications(user_id, max_notifications=35):
    """
    Keep only the most recent notifications per user.
    This prevents notification buildup in the database.
    """
    # Count total notifications for user
    total_count = Notifications.query.filter_by(user_id=user_id).count()
    
    if total_count > max_notifications:
        # Get IDs of notifications to keep (most recent 35)
        notifications_to_keep = db.session.query(Notifications.id).filter_by(
            user_id=user_id
        ).order_by(desc(Notifications.created_at)).limit(max_notifications).subquery()
        
        # Delete older notifications
        deleted_count = Notifications.query.filter_by(
            user_id=user_id
        ).filter(
            ~Notifications.id.in_(notifications_to_keep)
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        return deleted_count
    
    return 0

def create_notification(user_id, title, message):
    """
    Helper function to create a notification with automatic cleanup.
    Use this instead of creating Notifications directly.
    """
    # Import here to avoid circular import with socketio_events
    from app.socketio_events import send_notification_to_user
    
    # Create new notification with explicit timestamp
    created_at = datetime.utcnow()
    notification = Notifications(
        user_id=user_id,
        notif_title=title,
        notif_message=message,
        is_read=False,
        created_at=created_at
    )
    
    db.session.add(notification)
    db.session.commit()
    
    # Clean up old notifications after creating new one
    cleanup_old_notifications(user_id)
    
    # Send real-time notification with the timestamp we already have
    notification_data = {
        'id': notification.id,
        'title': title,
        'message': message,
        'created_at': created_at.isoformat()
    }
    send_notification_to_user(user_id, notification_data)
    
    return notification

# Context processor to make notifications available in dropdown
@community_bp.context_processor
def inject_notifications():
    """Inject notification data into community templates for dropdown only"""
    if current_user.is_authenticated:
        # Get recent unread notifications (for dropdown - limit to 5)
        notifications = Notifications.query.filter_by(
            user_id=current_user.id,
            is_read=False
        ).order_by(desc(Notifications.created_at)).limit(5).all()
        
        # Get unread count
        unread_count = Notifications.query.filter_by(
            user_id=current_user.id,
            is_read=False
        ).count()
        
        # Add icon and category for display
        for notification in notifications:
            if 'application' in notification.notif_title.lower():
                notification.icon = 'fa-file-alt'
                notification.icon_type = 'success'
            elif 'approved' in notification.notif_title.lower():
                notification.icon = 'fa-check-circle'
                notification.icon_type = 'success'
            elif 'rejected' in notification.notif_title.lower():
                notification.icon = 'fa-times-circle'
                notification.icon_type = 'danger'
            elif 'reminder' in notification.notif_title.lower():
                notification.icon = 'fa-clock'
                notification.icon_type = 'warning'
            else:
                notification.icon = 'fa-info-circle'
                notification.icon_type = 'info'
        
        return {
            'notifications': notifications,
            'unread_notifications_count': unread_count
        }
    
    return {
        'notifications': [],
        'unread_notifications_count': 0
    }