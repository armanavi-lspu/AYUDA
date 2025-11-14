from flask import render_template
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required

@admin_bp.route('/announcements/add', endpoint='add_announcements')
@login_required
@role_required('admin')
def announcements():
    return render_template('admin/add_announcements.html', user=current_user)
