import os
import sys
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = 'Run an automated enterprise production readiness and security compliance audit.'

    def handle(self, *args, **options):
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.HTTP_INFO("UNIVERSITY TASK MANAGEMENT PLATFORM -- PRODUCTION READINESS AUDIT"))
        self.stdout.write("=" * 70)

        checks_passed = 0
        checks_warned = 0
        checks_failed = 0

        def report(status, title, detail=""):
            nonlocal checks_passed, checks_warned, checks_failed
            if status == "PASS":
                checks_passed += 1
                icon = self.style.SUCCESS("[ PASS ]")
            elif status == "WARN":
                checks_warned += 1
                icon = self.style.WARNING("[ WARN ]")
            else:
                checks_failed += 1
                icon = self.style.ERROR("[ FAIL ]")
            self.stdout.write(f"{icon} {title}")
            if detail:
                self.stdout.write(f"         --> {detail}")

        # 1. DEBUG MODE
        if not settings.DEBUG:
            report("PASS", "DEBUG Mode is disabled (DEBUG = False)")
        else:
            report("WARN", "DEBUG is True (Must be False in actual production environment)")

        # 2. SECRET_KEY
        sec_key = getattr(settings, 'SECRET_KEY', '')
        if sec_key and not sec_key.startswith('django-insecure') and len(sec_key) >= 40:
            report("PASS", f"SECRET_KEY entropy is sufficient ({len(sec_key)} chars)")
        else:
            report("WARN", "SECRET_KEY uses default or low-entropy key", "Ensure env SECRET_KEY is set in production.")

        # 3. ALLOWED_HOSTS
        allowed = getattr(settings, 'ALLOWED_HOSTS', [])
        if allowed and '*' not in allowed:
            report("PASS", f"ALLOWED_HOSTS configured: {allowed}")
        elif '*' in allowed:
            report("WARN", "ALLOWED_HOSTS contains wildcard '*'", "Restrict to specific domain names in production.")
        else:
            report("FAIL", "ALLOWED_HOSTS is empty")

        # 4. DATABASE & MIGRATIONS
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            report("PASS", f"Database connection active: {settings.DATABASES['default']['ENGINE'].split('.')[-1]}")
            
            # Check migrations
            executor = MigrationExecutor(connection)
            unapplied = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if not unapplied:
                report("PASS", "Database schema is fully migrated (0 pending migrations)")
            else:
                report("FAIL", f"{len(unapplied)} unapplied migrations detected", "Run 'python manage.py migrate'")
        except Exception as e:
            report("FAIL", "Database connectivity failure", str(e))

        # 5. SECURITY MIDDLEWARE
        middleware = getattr(settings, 'MIDDLEWARE', [])
        sec_headers_present = 'core.middleware.SecurityHeadersMiddleware' in middleware
        rate_limit_present = 'core.middleware.RateLimitingMiddleware' in middleware
        if sec_headers_present:
            report("PASS", "SecurityHeadersMiddleware (HSTS, CSP, X-Frame-Options) is active")
        else:
            report("WARN", "SecurityHeadersMiddleware is missing from MIDDLEWARE")

        if rate_limit_present:
            report("PASS", "RateLimitingMiddleware (Brute-force & API protection) is active")
        else:
            report("WARN", "RateLimitingMiddleware is missing from MIDDLEWARE")

        # 6. COOKIE & CSRF SECURITY
        csrf_secure = getattr(settings, 'CSRF_COOKIE_SECURE', False)
        session_secure = getattr(settings, 'SESSION_COOKIE_SECURE', False)
        if csrf_secure and session_secure:
            report("PASS", "Session & CSRF cookies require HTTPS (SECURE=True)")
        else:
            report("WARN", "Session/CSRF cookies SECURE flag is False", "Set CSRF_COOKIE_SECURE and SESSION_COOKIE_SECURE = True when SSL is active.")

        # 7. STATIC & MEDIA ROOT
        static_root = getattr(settings, 'STATIC_ROOT', None)
        if static_root and os.path.isabs(str(static_root)):
            report("PASS", f"STATIC_ROOT defined: {static_root}")
        else:
            report("WARN", "STATIC_ROOT not configured for collectstatic")

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if media_root and os.path.exists(str(media_root)):
            report("PASS", f"MEDIA_ROOT directory accessible: {media_root}")
        else:
            report("WARN", f"MEDIA_ROOT path check: {media_root}")

        # 8. INSTALLED APPS (PHASES 1 - 15)
        expected_apps = [
            'core', 'accounts', 'organization', 'tasks', 'workflow', 'files',
            'hr', 'kpi', 'payroll', 'signatures', 'analytics',
            'automation', 'communication', 'operations', 'ai_assistant'
        ]
        installed = getattr(settings, 'INSTALLED_APPS', [])
        missing_apps = [app for app in expected_apps if app not in installed]
        if not missing_apps:
            report("PASS", f"All {len(expected_apps)} Enterprise Module Apps registered in INSTALLED_APPS")
        else:
            report("FAIL", f"Missing apps: {missing_apps}")

        # SUMMARY
        self.stdout.write("-" * 70)
        total = checks_passed + checks_warned + checks_failed
        score = (checks_passed / total * 100) if total > 0 else 0
        self.stdout.write(f"Readiness Score: {score:.1f}% ({checks_passed} Passed, {checks_warned} Warnings, {checks_failed} Failed)")
        
        if checks_failed == 0:
            self.stdout.write(self.style.SUCCESS("[OK] PRODUCTION AUDIT PASSED: System is ready for enterprise deployment."))
        else:
            self.stdout.write(self.style.ERROR("[X] PRODUCTION AUDIT FAILED: Resolve failed checks before production deployment."))
