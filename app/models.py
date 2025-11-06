from . import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy.sql import func

class JsonSerializableMixin:
    """Mixin to make models JSON serializable"""
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class User(db.Model, UserMixin):
    __tablename__ = 'users'     
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)  
    password_hash = db.Column(db.String(150), nullable=False)  
    first_name = db.Column(db.String(150), nullable=False)
    middle_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False, index=True)
    profile_pic = db.Column(db.String(255))
    last_activity = db.Column(db.DateTime)    
    
    programs = db.relationship('Programs', backref='user', lazy=True, cascade='all, delete-orphan')

class Programs(db.Model):
    __tablename__ = 'programs'
    
    id = db.Column(db.Integer, primary_key=True)
    program_name = db.Column(db.String(200), nullable=False)
    program_type = db.Column(db.String(50), nullable=False)
    program_period = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.DateTime(timezone=True), default=func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)