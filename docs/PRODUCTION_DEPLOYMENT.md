# Production Deployment & Infrastructure Guide (Phase 15)

## 1. System Requirements & Stack
- **OS**: Ubuntu 22.04 LTS / Debian 12 / Enterprise Linux
- **Language**: Python 3.12+
- **Application Framework**: Django 6.1
- **WSGI / ASGI Server**: Gunicorn / Uvicorn (with gevent/async workers)
- **Reverse Proxy & SSL**: Nginx / HAProxy / Traefik with TLS 1.3
- **Primary Database**: PostgreSQL 16+ (or enterprise-compatible SQL engine)
- **Cache & Message Broker**: Redis 7.x

## 2. Environment Configuration (`.env`)
```bash
# Core Django
DJANGO_SETTINGS_MODULE=config.settings
DEBUG=False
SECRET_KEY=enter-a-high-entropy-random-string-at-least-50-characters
ALLOWED_HOSTS=tasks.university.edu.uz,localhost,127.0.0.1

# Database Configuration
DATABASE_URL=postgres://task_user:StrongPassword@127.0.0.1:5432/university_tasks_db

# Security & SSL
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

# Static & Media Storage
STATIC_ROOT=/var/www/university_tasks/static/
MEDIA_ROOT=/var/www/university_tasks/media/

# Integrations
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
HEMIS_API_ENDPOINT=https://hemis.university.uz/api/v1
HEMIS_API_KEY=your-hemis-bearer-token
```

## 3. Gunicorn Systemd Service Unit
Create `/etc/systemd/system/university-tasks.service`:
```ini
[Unit]
Description=University Task Management Platform (Gunicorn)
After=network.target postgresql.service redis.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/university_tasks
ExecStart=/var/www/university_tasks/.venv/bin/gunicorn config.wsgi:application \
          --workers 4 \
          --bind 127.0.0.1:8000 \
          --timeout 120 \
          --access-logfile /var/log/university_tasks/access.log \
          --error-logfile /var/log/university_tasks/error.log

Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

## 4. Automation Scheduler Daemon Service Unit
Create `/etc/systemd/system/university-tasks-scheduler.service`:
```ini
[Unit]
Description=University Task Management Automation Scheduler Daemon
After=network.target university-tasks.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/university_tasks
ExecStart=/var/www/university_tasks/.venv/bin/python manage.py run_automation_scheduler --loop --interval 60
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

## 5. Nginx Production Configuration
Create `/etc/nginx/sites-available/university_tasks.conf`:
```nginx
server {
    listen 80;
    server_name tasks.university.edu.uz;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name tasks.university.edu.uz;

    ssl_certificate /etc/letsencrypt/live/tasks.university.edu.uz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tasks.university.edu.uz/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 50M;

    location /static/ {
        alias /var/www/university_tasks/static/;
        expires 30d;
        access_log off;
    }

    location /media/ {
        alias /var/www/university_tasks/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 6. Pre-Launch Deployment Checklist
1. `python manage.py collectstatic --noinput`
2. `python manage.py migrate`
3. `python manage.py production_readiness_check`
4. `systemctl daemon-reload && systemctl restart university-tasks university-tasks-scheduler nginx`
