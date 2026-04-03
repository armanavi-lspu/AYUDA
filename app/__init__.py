from flask import Flask
from pathlib import Path
from flask_login import LoginManager
from dotenv import load_dotenv

# Load environment variables for all app entry points (CLI, tests, WSGI, scripts)
load_dotenv()

from config import Config
from app.extensions import db, migrate

def create_app():
    root_path = Path(__file__).parent.parent
    
    app = Flask(__name__, 
                template_folder=str(root_path / "templates"),
                static_folder=str(root_path / "static"))
    
    app.config.from_object(Config)
    
    # Set timezone in app config
    import pytz
    app.config['TZ'] = pytz.timezone(app.config.get('TIMEZONE', 'Asia/Manila'))
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

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

    return app