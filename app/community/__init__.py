from flask import Blueprint

community = Blueprint('community', __name__, url_prefix='/community')

from .routes import dashboard