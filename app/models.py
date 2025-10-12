from . import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy.sql import func

class JsonSerializableMixin:
    """Mixin to make models JSON serializable"""
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class users(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False, index =True)
    password_hash = db.Column(db.String(150), nullable=False)
    first_name = db.Column(db.String(150), nullable=False)
    middle_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False, index = True)
    profile_pic = db.Column(db.String(255))

    # New field to track last activity
    last_activity = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Fixed relationship with proper backref and foreign key
    programs = db.relationship('Programs')

class Programs(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    program_name = db.Column(db.String(200))
    program_type = db.Column(db.String(50))
    program_period = db.Column(db.String(50))
    date = db.Column(db.DateTime(timezone=True), default=func.now())
    # Add foreign key to link with User
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


