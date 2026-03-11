from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# import routes after blueprint creation
from .routes import dashboard, adm_announcements, adm_programs, analytics
from .routes import admin_management, community, applications
from .routes import assessment, notifications, profile
