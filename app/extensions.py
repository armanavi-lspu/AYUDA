from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO

db = SQLAlchemy()
# Note: CORS should be restricted to specific origins in production
# Update this in production: socketio = SocketIO(cors_allowed_origins=["https://your-domain.com"])
socketio = SocketIO(cors_allowed_origins="*")
