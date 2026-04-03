import os
import pytz

class Config:
    # Database: Use DATABASE_URL env var (required for production)
    # Format: postgresql://user:password@host:port/database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:011523@localhost/Ayuda'  # Local dev default only
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Security: SECRET_KEY should be strong random string in production
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
    
    # Database connection pooling for production
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,  # Recycle connections every hour
        'pool_pre_ping': True,  # Test connection before using
    }
    
    # Timezone configuration (defaults to Asia/Manila for Philippines)
    TIMEZONE = os.environ.get('TIMEZONE', 'Asia/Manila')
    TZ = pytz.timezone(TIMEZONE)