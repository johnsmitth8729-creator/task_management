import contextvars
import time
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils.translation import gettext_lazy as _

_active_year_var = contextvars.ContextVar('active_year_var', default=None)


def get_current_active_year():
    return _active_year_var.get()


def set_current_active_year(year):
    return _active_year_var.set(year)


def reset_current_active_year(token):
    if token:
        _active_year_var.reset(token)


class ActiveYearMiddleware:
    """
    Sets the active working year for the current request context.
    Allows querysets (e.g. get_scoped_tasks) to automatically scope their results
    to the user's active working year.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        active_year = None
        if hasattr(request, 'session'):
            session_val = request.session.get('active_year')
            if session_val:
                try:
                    active_year = int(session_val)
                except (ValueError, TypeError):
                    active_year = None

        token = set_current_active_year(active_year)
        try:
            response = self.get_response(request)
        finally:
            reset_current_active_year(token)
        return response


class SecurityHeadersMiddleware:
    """
    Enforces enterprise security headers across all web responses.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Standard Security Headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
        response['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
        response['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://fonts.googleapis.com https://fonts.gstatic.com;"

        return response


class RateLimitingMiddleware:
    """
    Protects authentication and sensitive API endpoints against brute force and DDoS.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.rate_limit_paths = {
            '/accounts/login/': (30, 60),  # 30 requests per 60 seconds
            '/health/': (120, 60),          # 120 requests per 60 seconds
        }

    def __call__(self, request):
        path = request.path
        client_ip = self._get_client_ip(request)

        for limit_path, (max_requests, window_seconds) in self.rate_limit_paths.items():
            if path.startswith(limit_path):
                cache_key = f"rate_limit:{client_ip}:{limit_path}"
                request_count = cache.get(cache_key, 0)

                if request_count >= max_requests:
                    return JsonResponse(
                        {
                            'status': 'ERROR',
                            'error': 'Too Many Requests',
                            'message': _('Rate limit exceeded. Please wait before retrying.')
                        },
                        status=429
                    )

                if request_count == 0:
                    cache.set(cache_key, 1, timeout=window_seconds)
                else:
                    cache.incr(cache_key)

        return self.get_response(request)

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '127.0.0.1')


class CustomErrorPageMiddleware:
    """
    Ensures that custom branded 404 and 403 error pages are always displayed
    consistently across both development (DEBUG=True) and production (DEBUG=False)
    whenever an invalid link, missing resource, or permission denial occurs.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # In development mode, Django debug view overrides 404 and 403 with technical trace pages.
        # We replace them with our university custom error templates for page routes.
        if settings.DEBUG:
            if response.status_code == 404:
                if not request.path.startswith('/static/') and not request.path.startswith('/media/'):
                    from core.views import custom_404
                    return custom_404(request)
            elif response.status_code == 403:
                from core.views import custom_403
                return custom_403(request)

        return response
