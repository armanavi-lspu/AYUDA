from flask import Blueprint

admin = Blueprint('admin', __name__, url_prefix='/admin')

from .routes import dashboard, adm_programs, adm_announcements
from .routes import adm_users, adm_audit_logs
from .routes import analytics
