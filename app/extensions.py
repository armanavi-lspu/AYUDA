"""Flask extensions initialization"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
socketio = SocketIO(async_mode='eventlet', cors_allowed_origins='*')
