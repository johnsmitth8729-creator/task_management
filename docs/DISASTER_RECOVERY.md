# Disaster Recovery, Backups & System Health Monitoring (Phase 15)

## 1. Overview & Recovery Objectives
- **RPO (Recovery Point Objective)**: < 1 hour (Automated hourly JSON/SQL snapshots).
- **RTO (Recovery Time Objective)**: < 15 minutes (Direct single-command restoration with checksum validation).

## 2. Automated Database Backup Engine
The platform includes an automated backup command:
```bash
python manage.py backup_database --tag hourly --output-dir /var/backups/task_platform/
```

### Backup Artifacts:
1. `backup_YYYYMMDD_HHMMSS_hourly.json`: Natural key serialized database dump.
2. `backup_YYYYMMDD_HHMMSS_hourly_meta.json`: Cryptographic manifest containing SHA256 checksum, byte count, database engine, and timestamp.

## 3. Database Restore Pipeline
```bash
# Restore latest verified backup with automated SHA256 integrity verification:
python manage.py restore_database --latest --noinput

# Restore a specific backup archive:
python manage.py restore_database --file /var/backups/task_platform/backup_20260904_120000.json
```

## 4. Kubernetes / Docker Health & Probe Endpoints
The platform exposes standardized probe endpoints:
- **Liveness Probe**: `GET /health/live/` (HTTP 200 "OK") — Validates worker thread responsiveness.
- **Readiness Probe**: `GET /health/ready/` (HTTP 200 "READY" / HTTP 503 "UNAVAILABLE") — Validates live database connectivity via SQL ping.
- **Comprehensive Health Check**: `GET /health/` (JSON payload) — Reports granular component status for DB, Cache, and Python runtime.

## 5. Automated Health Audit Command
```bash
python manage.py production_readiness_check
```
Audits 8 critical dimensions: DEBUG status, SECRET_KEY entropy, ALLOWED_HOSTS, DB connectivity, schema migration status, security middleware, cookie flags, and app module registration.
