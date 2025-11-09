from flask import render_template
from flask_login import login_required, current_user
from .. import admin_bp
from app import admin

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('admin/dashboard.html', user=current_user)