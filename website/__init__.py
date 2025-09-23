from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager
import os
try:
    import psycopg  # type: ignore
    _PG_DRIVER = 'psycopg'
except Exception:
    _PG_DRIVER = None

db = SQLAlchemy()
DB_NAME = "database.db"

def create_app():
    # Use instance_relative_config so instance/ at project root is used
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = 'burat of tinga'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Prefer DATABASE_URL (e.g., for PostgreSQL); fallback to local SQLite for dev
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        # Normalize legacy scheme used by some providers
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        # Prefer psycopg v3 driver when available
        if database_url.startswith('postgresql://') and _PG_DRIVER and 'postgresql+' not in database_url:
            database_url = database_url.replace('postgresql://', f'postgresql+{_PG_DRIVER}://', 1)
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        # Store sqlite DB in Flask instance folder
        os.makedirs(app.instance_path, exist_ok=True)
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(app.instance_path, DB_NAME)}"
    db.init_app(app)



    from .views import views
    from .auth import auth

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')

    from .models import User, Note

    create_database(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id)) 

    return app


def create_database(app):
    # For SQLite, create the file once; for other DBs (e.g., PostgreSQL), ensure tables exist
    with app.app_context():
        uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if uri.startswith('sqlite:///'):
            sqlite_path = uri.replace('sqlite:///', '', 1)
            if not path.exists(sqlite_path):
                db.create_all()
                print('Created SQLite database!')
        else:
            db.create_all()
            print('Ensured tables exist on the configured database!')