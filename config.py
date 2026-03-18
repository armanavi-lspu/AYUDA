import os
import pytz

class Config:
    SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:011523@localhost/Ayuda'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'ratburn'
    
    # Timezone configuration (defaults to Asia/Manila for Philippines)
    # Change this to match your timezone (e.g., 'America/New_York', 'Europe/London')
    TIMEZONE = os.environ.get('TIMEZONE', 'Asia/Manila')
    TZ = pytz.timezone(TIMEZONE)