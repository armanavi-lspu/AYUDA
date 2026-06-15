import click
from flask.cli import with_appcontext
from app import db
from datetime import datetime, timedelta
import random
from werkzeug.security import generate_password_hash
from app.models import User, Programs, Applications, CommunityUsers, AdminUsers

@click.command('populate-dummy-data')
@with_appcontext
def populate_dummy_data_command():
    """Populate database with dummy data for testing"""
    # (Copy the populate_dummy_data function content here)
    click.echo('Populating dummy data...')
    # ... rest of the code ...
    click.echo('Done!')

def init_app(app):
    app.cli.add_command(populate_dummy_data_command)