# Gunicorn config for AYUDA

bind = "127.0.0.1:8000"

# Socket.IO without a message broker should run with a single worker.
workers = 1
worker_class = "eventlet"

# WebSocket and DB-heavy requests may run longer.
timeout = 180
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "/var/log/ayuda/access.log"
errorlog = "/var/log/ayuda/error.log"
loglevel = "info"
capture_output = True

# Performance tuning
preload_app = False
max_requests = 500
max_requests_jitter = 50
