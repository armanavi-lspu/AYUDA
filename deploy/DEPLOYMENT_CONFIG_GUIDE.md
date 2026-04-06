# AYUDA Production Deployment Configuration

## Server Details
- **Instance**: AWS Lightsail (Singapore region)
- **IP Address**: 54.251.197.243
- **Domain**: ayudaportal.website
- **Database**: PostgreSQL 11+ RDS (Singapore ap-southeast-1)

## Configuration Files Location

### Nginx
**Local Path**: `nginx-ayuda.conf`  
**Server Path**: `/etc/nginx/sites-available/ayuda`  
**Status**: Active (symlinked to `/etc/nginx/sites-enabled/ayuda`)

Includes websocket proxy support for `/socket.io/` with HTTP upgrade headers.

**Setup Commands**:
```bash
sudo cp nginx-ayuda.conf /etc/nginx/sites-available/ayuda
sudo ln -s /etc/nginx/sites-available/ayuda /etc/nginx/sites-enabled/ayuda
sudo nginx -t
sudo systemctl restart nginx
```

### Systemd Service
**Local Path**: `ayuda.service`  
**Server Path**: `/etc/systemd/system/ayuda.service`

**Setup Commands**:
```bash
sudo cp ayuda.service /etc/systemd/system/ayuda.service
sudo systemctl daemon-reload
sudo systemctl enable ayuda
sudo systemctl start ayuda
```

## Gunicorn Configuration

**Local Path**: `gunicorn.conf.py`  
**Server Path**: `/var/www/ayuda/deploy/gunicorn.conf.py`

**Worker Class**: eventlet  
**Workers**: 2  
**Timeout**: 180 seconds  
**Graceful Timeout**: 30 seconds  
**Keepalive**: 5 seconds  
**Bind Address**: 127.0.0.1:8000

**Worker Recycling**: max_requests=500, max_requests_jitter=50

**Log Files**:
- `/var/log/ayuda/access.log`
- `/var/log/ayuda/error.log`

**Configuration Details**:
- Application serves on localhost:8000
- Nginx acts as reverse proxy on ports 80 (HTTP) and 443 (HTTPS)
- SSL certificates from Let's Encrypt at `/etc/letsencrypt/live/ayudaportal.website/`

**Required Command in systemd**:
```bash
ExecStart=/var/www/ayuda/.venv/bin/gunicorn --config /var/www/ayuda/deploy/gunicorn.conf.py wsgi:app
```

## SSL Certificate Information
- **Issued To**: ayudaportal.website, www.ayudaportal.website
- **Expiry**: July 3, 2026
- **Certificate Path**: `/etc/letsencrypt/live/ayudaportal.website/fullchain.pem`
- **Private Key Path**: `/etc/letsencrypt/live/ayudaportal.website/privkey.pem`

## Service Management

```bash
# View service status
sudo systemctl status ayuda

# View logs
sudo journalctl -u ayuda -f

# Restart service
sudo systemctl restart ayuda

# Stop service
sudo systemctl stop ayuda

# Start service
sudo systemctl start ayuda

# Check nginx status
sudo systemctl status nginx

# Verify nginx config
sudo nginx -t
```

## Environment Configuration
- **Server Environment**: `/var/www/ayuda/.env`
- **Key Variables**:
  - `DATABASE_URL`: PostgreSQL RDS endpoint (Singapore region)
  - `FLASK_ENV`: production
  - `DEBUG`: False

## Database Connection
- **Host**: RDS endpoint (Singapore ap-southeast-1)
- **Port**: 5432
- **Database**: flask_db (or configured name)
- **User**: Database user from .env

## Useful SSH Commands

```bash
# Connect to server
ssh ubuntu@54.251.197.243

# Activate virtual environment
source /var/www/ayuda/.venv/bin/activate

# View app directory
ls -la /var/www/ayuda/

# Check if Gunicorn is running
ps aux | grep gunicorn

# Monitor service
watch sudo systemctl status ayuda
```

## Firewall Rules
Ensure these ports are open in Lightsail security group:
- **22/tcp** (SSH)
- **80/tcp** (HTTP)
- **443/tcp** (HTTPS)

## Deployment History
- **Database**: Migrated from us-east-1 RDS to Singapore ap-southeast-1 RDS for latency optimization
- **SSL**: Let's Encrypt certificates configured
- **Domain**: Namecheap DNS configured with A records
- **Database Migrations**: All applied successfully (head: multiple_copy_types)
