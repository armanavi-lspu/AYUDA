from flask import render_template
from flask_login import login_required, current_user
from app.admin import admin_bp
from app.utils import role_required

@admin_bp.route('/other_services', endpoint='adm_other_services')
@login_required
@role_required('admin')
def other_services():
    return render_template('admin/adm_other_services.html', user=current_user)
