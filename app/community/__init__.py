from flask import Blueprint

community_bp = Blueprint('community', __name__, url_prefix='/community')

# Import routes after blueprint creation to avoid circular imports
from .routes import dashboard, announcements, applications, programs, notifications, other_services  