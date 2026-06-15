from flask_socketio import emit, join_room, leave_room
from flask_login import current_user
from app.extensions import db, socketio


def _serialize_notification(notification):
    """Build a compact notification payload for socket events."""
    return {
        'id': notification.id,
        'title': notification.notif_title,
        'message': notification.notif_message,
        'is_read': notification.is_read,
        'related_id': notification.related_id,
        'related_type': notification.related_type,
        'created_at': notification.created_at.isoformat() if notification.created_at else None,
    }


def emit_notification_created(notification):
    """Emit a new-notification event to the owner room."""
    socketio.emit('new_notification', _serialize_notification(notification), room=f'user_{notification.user_id}')


def emit_notification_updated(notification):
    """Emit a notification-updated event to the owner room."""
    socketio.emit('notification_updated', _serialize_notification(notification), room=f'user_{notification.user_id}')


def emit_admin_dashboard_update(payload=None):
    """Emit admin dashboard data update event."""
    socketio.emit('admin_dashboard_update', payload or {'changed': True}, room='admins')


def emit_admin_analytics_update(payload=None):
    """Emit admin analytics data update event."""
    socketio.emit('admin_analytics_update', payload or {'changed': True}, room='admins')


def emit_community_dashboard_update(payload=None):
    """Emit community dashboard data update event."""
    socketio.emit('community_dashboard_update', payload or {'changed': True}, room='community_users')


def emit_application_workflow_update(payload=None):
    """Emit application workflow updates to admins and the affected community user."""
    event_payload = payload or {'changed': True}
    socketio.emit('application_workflow_update', event_payload, room='admins')

    if event_payload.get('user_id'):
        socketio.emit('application_workflow_update', event_payload, room=f"user_{event_payload['user_id']}")
    else:
        socketio.emit('application_workflow_update', event_payload, room='community_users')

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        if current_user.role in {'admin', 'super_admin'}:
            join_room('admins')
        elif current_user.role == 'community':
            join_room('community_users')
        print(f'User {current_user.id} connected')
        emit('connection_response', {'status': 'connected', 'role': current_user.role})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    if current_user.is_authenticated:
        leave_room(f'user_{current_user.id}')
        if current_user.role in {'admin', 'super_admin'}:
            leave_room('admins')
        elif current_user.role == 'community':
            leave_room('community_users')
        print(f'User {current_user.id} disconnected')

@socketio.on('mark_notification_read')
def handle_mark_read(data):
    """Mark notification as read"""
    if not current_user.is_authenticated:
        return

    from app.models import Notifications
    
    notification_id = data.get('notification_id')
    notification = Notifications.query.filter_by(
        id=notification_id, 
        user_id=current_user.id
    ).first()
    
    if notification:
        notification.is_read = True
        db.session.commit()
        emit_notification_updated(notification)

def send_notification_to_user(user_id, notification_data):
    """Send real-time notification to specific user"""
    socketio.emit('new_notification', notification_data, room=f'user_{user_id}')