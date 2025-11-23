from flask_socketio import emit, join_room, leave_room
from flask_login import current_user
from app import socketio
from app.extensions import db
from app.models import Notifications

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        print(f'User {current_user.id} connected')
        emit('connection_response', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    if current_user.is_authenticated:
        leave_room(f'user_{current_user.id}')
        print(f'User {current_user.id} disconnected')

@socketio.on('mark_notification_read')
def handle_mark_read(data):
    """Mark notification as read"""
    if not current_user.is_authenticated:
        return
    
    notification_id = data.get('notification_id')
    notification = Notifications.query.filter_by(
        id=notification_id, 
        user_id=current_user.id
    ).first()
    
    if notification:
        notification.is_read = True
        db.session.commit()
        emit('notification_updated', {'notification_id': notification_id, 'status': 'read'})

def send_notification_to_user(user_id, notification_data):
    """Send real-time notification to specific user"""
    socketio.emit('new_notification', 
                  notification_data, 
                  room=f'user_{user_id}')