from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == '__main__':
    # NEVER use debug=True in production
    # For production, use WSGI server like Gunicorn instead
    import os
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    # Flask-SocketIO + eventlet on Windows can fail with WinError 10048 when
    # the debug reloader attempts a second bind in a child process.
    socketio.run(app, host=host, port=port, debug=debug_mode, use_reloader=False)