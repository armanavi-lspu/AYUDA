from flask import Blueprint, render_template, request, flash, jsonify, views
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app.models import Programs
from app.admin import admin_bp
from app.extensions import db
from app.utils import role_required


@admin_bp.route('/programs', endpoint='adm_programs')  # list/index page
@login_required
@role_required(['admin'])
def programs_index():
    return render_template('admin/adm_programs.html')