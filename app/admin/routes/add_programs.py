from flask import Blueprint, render_template, request, flash, jsonify, views, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app.models import Programs
from app.admin import admin_bp
from app.models import (
    Programs, User
)
from app.extensions import db
from app.utils import role_required
import json

@admin_bp.route('/programs/add', endpoint='add_program')  # create page
@login_required
@role_required(['admin'])
def add_program():
    return render_template('admin/add_programs.html')

