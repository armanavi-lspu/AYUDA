from flask import render_template
from flask_login import login_required, current_user
from app.community import community_bp
from app.utils import role_required

@community_bp.route('/notifications')
@login_required
@role_required('community')
def notifications():
    return render_template('community/notifications.html', user=current_user)