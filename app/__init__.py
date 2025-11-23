from flask import Flask
from pathlib import Path
from flask_login import LoginManager
from config import Config
from app.extensions import db

def create_app():
    root_path = Path(__file__).parent.parent
    
    app = Flask(__name__, 
                template_folder=str(root_path / "templates"),
                static_folder=str(root_path / "static"))
    
    app.config.from_object(Config)
    db.init_app(app)

    # Import and register blueprints
    from .auth.auth import auth_bp
    from .admin import admin_bp
    from .community import community_bp  
    from .home.routes import home_bp
    
    app.register_blueprint(auth_bp, url_prefix='/')
    app.register_blueprint(admin_bp)
    app.register_blueprint(community_bp)  
    app.register_blueprint(home_bp)
    
    from .models import User, Programs
    
    with app.app_context():
        db.create_all()

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    return app