from flask import render_template, redirect, flash, url_for, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import desc
from app.admin import admin_bp
from app.models import (
    Programs, User
)
from app.extensions import db
from app.utils import role_required


@admin_bp.route('/dashboard')
@login_required
@role_required(['admin'])
def dashboard():
    
    today = datetime.utcnow()

    return render_template('admin/dashboard.html', user=current_user)