from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config

db = SQLAlchemy()

def create_app():
    app = Flask(__name__, template_folder='../templates',
                static_folder='../static')
    app.config.from_object(Config)
    db.init_app(app)

    from .views import views
    from .auth.auth import auth
    from .recommendations_api import recommendations_bp

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')
    app.register_blueprint(recommendations_bp)

    # Import the models with correct names
    from .models import User, Programs, UserProgramInteraction
    
    with app.app_context():
        db.create_all()

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    return app