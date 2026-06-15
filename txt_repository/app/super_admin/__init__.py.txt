from flask import Blueprint


super_admin_bp = Blueprint('super_admin', __name__, url_prefix='/super-admin')

# Import routes after blueprint creation to avoid circular imports.
from . import routes
from . import admin_management
from . import analytics
