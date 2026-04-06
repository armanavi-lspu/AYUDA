from flask import Flask, request, jsonify, flash, redirect, url_for
from pathlib import Path
from flask_login import LoginManager, current_user
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFError
from urllib.parse import urlparse

# Load environment variables for all app entry points (CLI, tests, WSGI, scripts)
load_dotenv()

from config import Config
from app.extensions import db, migrate, csrf, socketio

def create_app():
    root_path = Path(__file__).parent.parent
    
    app = Flask(__name__, 
                template_folder=str(root_path / "templates"),
                static_folder=str(root_path / "static"))
    
    app.config.from_object(Config)
    
    # Set timezone in app config
    import pytz
    app.config['TZ'] = pytz.timezone(app.config.get('TIMEZONE', 'Asia/Manila'))

    from app.utils import manila_strftime
    app.jinja_env.filters['manila'] = manila_strftime
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    socketio.init_app(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        accepts_json = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html

        if is_ajax or accepts_json:
            return jsonify({
                'success': False,
                'message': 'Security token validation failed. Please refresh and try again.'
            }), 400

        flash('Security token validation failed. Please try again.', category='error')
        return redirect(request.referrer or url_for('auth.login'))

    @app.errorhandler(404)
    def handle_not_found(error):
        accept_header = (request.headers.get('Accept') or '').lower()
        wants_html = request.method == 'GET' and 'text/html' in accept_header
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        is_api_like = '/api/' in request.path or request.path.startswith('/socket.io')
        is_static_request = request.path.startswith('/static/')

        # Keep native 404 behavior for API/AJAX/static requests.
        if not wants_html or is_ajax or is_api_like or is_static_request:
            return error

        message = 'Page not found, page might be removed or deleted.'
        referrer = request.referrer
        if referrer:
            referrer_url = urlparse(referrer)
            current_host = urlparse(request.host_url)
            if referrer_url.netloc == current_host.netloc and referrer_url.path != request.path:
                flash(message, category='warning')
                return redirect(referrer)

        flash(message, category='warning')
        if current_user.is_authenticated:
            if current_user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            if current_user.role == 'community':
                return redirect(url_for('community.dashboard'))

        return redirect(url_for('main.about'))

    # Import and register blueprints
    from .auth.auth import auth_bp
    from .admin import admin_bp
    from .community import community_bp  
    from .home.routes import home_bp
    
    app.register_blueprint(auth_bp, url_prefix='/')
    app.register_blueprint(admin_bp)
    app.register_blueprint(community_bp)  
    app.register_blueprint(home_bp)
    
    # Import models to register them with SQLAlchemy
    from .models import User, Programs

    # Register CLI commands
    from . import cli
    cli.init_app(app)

    # Initialize Flask-Login

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    @app.context_processor
    def inject_notification_count():
        from flask_login import current_user
        if current_user.is_authenticated and current_user.role == 'admin':
            from app.models import Notifications
            count = Notifications.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
            return {'admin_unread_count': count}
        return {'admin_unread_count': 0}

    @app.before_request
    def update_last_activity():
        """Persist user activity timestamp for profile/admin metrics."""
        if not current_user.is_authenticated:
            return

        if request.endpoint in {None, 'static'}:
            return

        if request.path.startswith('/static/') or request.path.startswith('/socket.io'):
            return

        now = datetime.utcnow()
        previous_activity = current_user.last_activity

        # Throttle writes to reduce unnecessary updates on rapid requests.
        if previous_activity and (now - previous_activity) < timedelta(minutes=2):
            return

        try:
            current_user.last_activity = now
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Register Socket.IO handlers and SQLAlchemy realtime hooks.
    from . import socketio_events  # noqa: F401
    from . import realtime_hooks  # noqa: F401

    return app