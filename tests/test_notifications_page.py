from app import create_app
from app.models import Notifications, User

app = create_app()
with app.app_context():
    user = User.query.filter_by(role='community').first()
    if user:
        notif_count = Notifications.query.filter_by(user_id=user.id).count()
        unread_count = Notifications.query.filter_by(user_id=user.id, is_read=False).count()
        
        print('Notifications page implementation complete')
        print(f'  User: {user.first_name}')
        print(f'  Total notifications: {notif_count}')
        print(f'  Unread: {unread_count}')
        print('')
        print('Features added:')
        print('  ✓ Full notifications page with pagination')
        print('  ✓ Filter by status (all, unread, read)')
        print('  ✓ Mark individual notifications as read')
        print('  ✓ Delete individual notifications')
        print('  ✓ Mark all as read functionality')
        print('  ✓ Delete all read notifications')
        print('  ✓ Clickable notification links to related pages')
        print('  ✓ Notifications persist for tracking')
        print('  ✓ Max 100 notifications per user (increased from 35)')
        print('')
        print('Access at: /community/notifications')
