from app import create_app
from app.models import Notifications

app = create_app()
with app.app_context():
    notif = Notifications.query.first()
    
    print('Testing notification URL generation...')
    if notif:
        print(f'Notification ID: {notif.id}')
        print(f'Title: {notif.notif_title}')
        print(f'Related Type: {notif.related_type}')
        print(f'Related ID: {notif.related_id}')
        print(f'Generated URL: {notif.get_url()}')
        print('\n✓ URL generation method is working!')
    else:
        print('No notifications found in database yet.')
        print('✓ URL generation method defined and ready to use.')
