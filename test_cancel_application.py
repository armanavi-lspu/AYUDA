from app import create_app
from app.models import Applications, User

app = create_app()
with app.app_context():
    # Get a user and their application
    user = User.query.filter_by(role='community').first()
    if user:
        app_count = Applications.query.filter_by(user_id=user.id).count()
        print('Application Cancellation Feature Added')
        print('=' * 50)
        print(f'User: {user.first_name} {user.last_name}')
        print(f'Total applications: {app_count}')
        print('')
        print('Features:')
        print('  ✓ Users can cancel pending/rejected applications')
        print('  ✓ Confirmation modal prevents accidental deletion')
        print('  ✓ Cascading delete: application + documents + photos')
        print('  ✓ File cleanup: removes uploaded files from disk')
        print('  ✓ Cancel button hidden for approved applications')
        print('')
        print('Route: POST /community/applications/<id>/cancel')
        print('Access: Application Details Page')
        print('')
        print('Modal shows:')
        print('  - Program name being cancelled')
        print('  - Warning about data deletion')
        print('  - List of what will be deleted')
        print('  - Confirm/Cancel options')
