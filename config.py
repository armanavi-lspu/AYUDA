import os

class Config:
    SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:123456789@localhost/Ayuda'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'ratburn'