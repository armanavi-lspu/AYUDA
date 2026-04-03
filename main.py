from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

from app import create_app

app = create_app()

if __name__ == '__main__':
    # NEVER use debug=True in production
    # For production, use WSGI server like Gunicorn instead
    import os
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    app.run(debug=debug_mode) 