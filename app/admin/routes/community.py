from flask import render_template
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required

@admin_bp.route('/community')
@login_required
@role_required('admin')
def community():
    return render_template('admin/community.html', user=current_user)
