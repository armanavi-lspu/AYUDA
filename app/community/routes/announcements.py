from flask import render_template
from flask_login import login_required, current_user
from app.community import community_bp
from app.utils import role_required

@community_bp.route('/announcements')
@login_required
@role_required('community')
def announcements():
    return render_template('community/announcements.html', user=current_user)
