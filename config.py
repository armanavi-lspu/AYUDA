import os

class Config:
    SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:011523@localhost/AYUDA'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'ratburn'