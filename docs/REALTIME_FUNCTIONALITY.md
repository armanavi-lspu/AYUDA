# Real-Time Functionality Documentation

## Overview

The AYUDA system now includes real-time functionality using Flask-SocketIO, enabling instant updates for notifications, dashboard statistics, and application status changes without requiring page refreshes.

## Features Implemented

### 1. Real-Time Notifications
- **Instant Delivery**: Notifications are sent immediately to users when created
- **Toast Notifications**: Visual pop-up notifications appear on screen with slide-in animation
- **Badge Updates**: Notification counters update in real-time
- **Auto-dismiss**: Toast notifications automatically close after 5 seconds

### 2. Real-Time Dashboard Updates
- **Admin Dashboard**: Automatically refreshes when new applications are submitted or statuses change
- **Community Dashboard**: Updates application statistics and program information in real-time
- **Broadcast to Roles**: Updates can be sent to all admins or all community users simultaneously

### 3. Real-Time Application Updates
- **Status Changes**: Community users receive instant notifications when application status changes
- **Document Verification**: Real-time updates when documents are approved/rejected
- **Claim Scheduling**: Immediate notification when claim schedule is set

## Technical Implementation

### Backend Components

#### 1. SocketIO Initialization (`app/extensions.py`)
```python
from flask_socketio import SocketIO
socketio = SocketIO(cors_allowed_origins="*")
```

#### 2. Event Handlers (`app/socketio_events.py`)
- `handle_connect()`: Manages user connections and room assignments
- `handle_disconnect()`: Cleans up when users disconnect
- `send_notification_to_user()`: Sends notification to specific user
- `broadcast_dashboard_update()`: Broadcasts updates to role-based rooms
- `send_application_update()`: Sends application updates to users

#### 3. Integration Points
Real-time notifications are triggered at:
- Application status changes (`app/admin/routes/applications.py`)
- Document verification updates
- Claim schedule setting
- User account creation (`app/admin/routes/admin_management.py`, `app/admin/routes/community.py`)
- Password resets

### Frontend Components

#### 1. SocketIO Client Integration
Both `admin_base.html` and `community_base.html` include:
- Socket.IO JavaScript client library
- Connection management
- Event listeners for real-time updates
- Toast notification display function

#### 2. Event Listeners
- `new_notification`: Displays toast and updates badge count
- `application_update`: Shows update notification and reloads if needed
- `dashboard_update`: Triggers dashboard data refresh

## Usage Examples

### Sending a Real-Time Notification (Backend)
```python
from app.socketio_events import send_notification_to_user

# Create notification in database
notification = Notifications(
    user_id=user_id,
    notif_title='Application Approved',
    notif_message='Your application has been approved!',
    is_read=False
)
db.session.add(notification)
db.session.commit()

# Send real-time update
send_notification_to_user(user_id, {
    'id': notification.id,
    'title': notification.notif_title,
    'message': notification.notif_message,
    'created_at': notification.created_at.isoformat()
})
```

### Broadcasting Dashboard Update (Backend)
```python
from app.socketio_events import broadcast_dashboard_update

# After making changes that affect dashboard
broadcast_dashboard_update('admin')  # Notify all admins
# or
broadcast_dashboard_update('community')  # Notify all community users
```

### Handling Real-Time Updates (Frontend)
The JavaScript is already integrated in base templates and automatically handles:
- Displaying toast notifications
- Updating badge counts
- Reloading dashboard data
- Showing application updates

## Testing

Run the SocketIO tests:
```bash
python -m pytest tests/test_socketio.py -v
```

## Configuration

### CORS Settings
The SocketIO server is configured to accept connections from all origins:
```python
socketio = SocketIO(cors_allowed_origins="*")
```

For production, update this to specific allowed origins for security.

### Running the Server
The application must be run with SocketIO:
```python
# main.py
from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == '__main__': 
    socketio.run(app, debug=True)
```

## Security Considerations

1. **Authentication**: Only authenticated users can connect to SocketIO
2. **Room-Based Access**: Users are automatically assigned to user-specific and role-specific rooms
3. **Message Validation**: All incoming messages should be validated
4. **CORS**: Update CORS settings for production to restrict origins

## Browser Compatibility

The Socket.IO client is compatible with:
- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Future Enhancements

Potential improvements for future iterations:
1. Message queuing for offline users
2. Read receipts for notifications
3. Real-time chat between admins and community users
4. Real-time document upload progress
5. Live application review sessions
6. Push notifications for mobile devices

## Troubleshooting

### Connection Issues
- Verify SocketIO is properly initialized in `app/__init__.py`
- Check that Socket.IO client library is loaded in templates
- Ensure the server is running with `socketio.run()` not `app.run()`

### Notifications Not Appearing
- Check browser console for JavaScript errors
- Verify user is authenticated
- Confirm notification data structure matches expected format

### Dashboard Not Updating
- Ensure `broadcast_dashboard_update()` is called after data changes
- Check that user is in the correct role-based room
- Verify dashboard has update handling logic
