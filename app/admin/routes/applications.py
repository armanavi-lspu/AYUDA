from flask import render_template
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required

@admin_bp.route('/applications')
@login_required
@role_required('admin')
def applications():
    return render_template('admin/applications.html', user=current_user)
