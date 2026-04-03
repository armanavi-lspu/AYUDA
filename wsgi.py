"""
WSGI entry point for production deployment
Use with: gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Ensure FLASK_ENV is set to production
os.environ.setdefault('FLASK_ENV', 'production')

from app import create_app

app = create_app()

if __name__ == '__main__':
    # This should not be used directly in production
    # Use Gunicorn or other WSGI server instead
    app.run()

    
