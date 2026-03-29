from flask import jsonify, render_template, request
from flask_login import login_required, current_user
from app.community import community_bp
from app.utils import role_required
from app.models import Notifications
from app.extensions import db
from sqlalchemy import desc

@community_bp.route('/notifications', endpoint='notifications')
@login_required
@role_required('community')
def view_notifications():
    """Display all notifications for the current user with pagination and filtering"""
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
        elif 'announcement' in notification.notif_title.lower():
            notification.icon = 'fa-bullhorn'
            notification.icon_type = 'info'
        elif 'update' in notification.notif_title.lower():
            notification.icon = 'fa-sync-alt'
            notification.icon_type = 'info'
        else:
            notification.icon = 'fa-info-circle'
            notification.icon_type = 'info'
    
    # Get statistics
    total_count = Notifications.query.filter_by(user_id=current_user.id).count()
    unread_count = Notifications.query.filter_by(user_id=current_user.id, is_read=False).count()
    
    return render_template('community/notifications.html',
                         notifications=notifications,
                         paginated=paginated,
                         page=page,
                         per_page=per_page,
                         status_filter=status_filter,
                         total_count=total_count,
                         unread_count=unread_count)

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

@community_bp.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
@role_required('community')
def delete_notification(notification_id):
    """Delete a specific notification"""
    notification = Notifications.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first()
    
    if not notification:
        return jsonify({'success': False, 'message': 'Notification not found'}), 404
    
    db.session.delete(notification)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Notification deleted successfully'
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

@community_bp.route('/notifications/delete-all-read', methods=['POST'])
@login_required
@role_required('community')
def delete_all_read_notifications():
    """Delete all read notifications for the current user"""
    deleted_count = Notifications.query.filter_by(
        user_id=current_user.id,
        is_read=True
    ).delete()
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'count': deleted_count,
        'message': f'{deleted_count} read notifications deleted'
    })

def cleanup_old_notifications(user_id, max_notifications=100):
    """
    Keep only the most recent notifications per user.
    This prevents notification buildup in the database.
    Increased from 35 to 100 to allow better tracking.
    """
    # Count total notifications for user
    total_count = Notifications.query.filter_by(user_id=user_id).count()
    
    if total_count > max_notifications:
        # Get IDs of notifications to keep (most recent 100)
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

def create_notification(user_id, title, message, related_id=None, related_type=None):
    """
    Helper function to create a notification with automatic cleanup.
    Use this instead of creating Notifications directly.
    
    Args:
        user_id: ID of the user to notify
        title: Notification title
        message: Notification message
        related_id: ID of the related resource (optional)
        related_type: Type of related resource: 'application', 'announcement', 'program', etc. (optional)
    """
    # Create new notification
    notification = Notifications(
        user_id=user_id,
        notif_title=title,
        notif_message=message,
        is_read=False,
        related_id=related_id,
        related_type=related_type
    )
    
    db.session.add(notification)
    db.session.commit()
    
    # Clean up old notifications after creating new one
    cleanup_old_notifications(user_id)
    
    return notification

# Context processor to make notifications available in dropdown
@community_bp.context_processor
def inject_notifications():
    """Inject notification data into community templates for dropdown only"""
    if current_user.is_authenticated:
        # Get recent notifications (read and unread) for dropdown visibility
        notifications = Notifications.query.filter_by(
            user_id=current_user.id
        ).order_by(desc(Notifications.created_at)).limit(15).all()
        
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