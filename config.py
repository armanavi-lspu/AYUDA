import os
import pytz


def _parse_csrf_time_limit(raw_value):
    """Allow env-based override; default to no expiry to avoid long-form timeout failures."""
    if raw_value is None:
        return None

    value = str(raw_value).strip().lower()
    if value in ('', 'none', 'null', 'false'):
        return None

    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except ValueError:
        return None

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

    # CSRF protection for state-changing requests.
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = _parse_csrf_time_limit(os.environ.get('WTF_CSRF_TIME_LIMIT'))

    # Cookie defaults that help mitigate CSRF in browsers.
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    
    # Database connection pooling for production
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,  # Recycle connections every hour
        'pool_pre_ping': True,  # Test connection before using
    }
    
    # Timezone configuration (defaults to Asia/Manila for Philippines)
    TIMEZONE = os.environ.get('TIMEZONE', 'Asia/Manila')
    TZ = pytz.timezone(TIMEZONE)