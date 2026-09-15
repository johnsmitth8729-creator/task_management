from urllib.parse import unquote, urlsplit, urlunsplit
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.utils import timezone, translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, TemplateView, View

from accounts.models import Role, User
from accounts.permissions import RectorRequiredMixin
from core.models import AuditLog
from organization.models import Department, DepartmentResponsibility, Position


class LandingPageView(TemplateView):
    template_name = 'core/landing.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().get(request, *args, **kwargs)



class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'core/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Task Metrics scoped to user
        from tasks.services import get_scoped_tasks
        from tasks.models import Task
        scoped_tasks = get_scoped_tasks(user, include_archived=False)
        active_year = self.request.session.get('active_year')
        if active_year:
            try:
                scoped_tasks = scoped_tasks.filter(created_at__year=int(active_year))
            except (ValueError, TypeError):
                pass

        today = timezone.now().date()
        context['task_stats'] = {
            'total': scoped_tasks.count(),
            'active': scoped_tasks.filter(status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]).count(),
            'completed': scoped_tasks.filter(status=Task.Status.COMPLETED).count(),
            'overdue': scoped_tasks.filter(
                deadline__lt=today,
                status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS],
            ).count(),
            'draft': scoped_tasks.filter(status=Task.Status.DRAFT).count(),
        }

        completed_tasks = scoped_tasks.filter(status=Task.Status.COMPLETED)
        from signatures.models import ElectronicSignature
        signed_count = completed_tasks.filter(signatures__status=ElectronicSignature.Status.SIGNED).distinct().count()
        pending_signature_count = completed_tasks.exclude(signatures__status=ElectronicSignature.Status.SIGNED).count()

        context['signature_stats'] = {
            'completed': completed_tasks.count(),
            'signed': signed_count,
            'pending_signature': pending_signature_count,
        }
        context['recent_tasks'] = scoped_tasks.select_related('responsible_department', 'task_type').order_by('-created_at')[:6]

        if user.is_rector:
            context['total_departments'] = Department.objects.count()
            context['active_departments'] = Department.objects.filter(is_active=True).count()
            context['total_users'] = User.objects.count()
            context['active_users'] = User.objects.filter(is_active=True).count()
            context['inactive_users'] = User.objects.filter(is_active=False).count()
            context['total_positions'] = Position.objects.count()

            vr_role = Role.objects.filter(code=Role.Codes.VICE_RECTOR).first()
            context['total_vice_rectors'] = User.objects.filter(roles=vr_role, is_active=True).count() if vr_role else 0

            head_role = Role.objects.filter(code=Role.Codes.DEPARTMENT_HEAD).first()
            context['total_department_heads'] = User.objects.filter(roles=head_role, is_active=True).count() if head_role else 0

            emp_role = Role.objects.filter(code=Role.Codes.EMPLOYEE).first()
            context['total_employees'] = User.objects.filter(roles=emp_role, is_active=True).count() if emp_role else 0

            context['recent_audit_logs'] = AuditLog.objects.select_related('actor')[:8]
            context['departments_summary'] = Department.objects.filter(is_active=True).select_related('head').annotate(
                active_employee_count=Count('users', filter=Q(users__is_active=True)),
            ).order_by('-active_employee_count')[:6]

        elif user.is_vice_rector:
            scoped_depts = user.get_scoped_departments().filter(is_active=True).select_related('head').annotate(
                active_employee_count=Count('users', filter=Q(users__is_active=True)),
            )
            context['my_departments'] = scoped_depts
            context['total_scoped_departments'] = scoped_depts.count()
            scoped_users = user.get_scoped_users().filter(is_active=True)
            context['total_scoped_employees'] = scoped_users.count()
            context['scoped_department_heads'] = scoped_users.filter(roles__code=Role.Codes.DEPARTMENT_HEAD)

        elif user.is_department_head and user.department:
            dept = user.department
            context['my_department'] = dept
            context['department_employees'] = dept.users.filter(is_active=True).select_related('position').order_by('first_name', 'last_name')
            context['department_positions'] = dept.positions.filter(is_active=True)
            context['total_department_employees'] = dept.users.filter(is_active=True).count()
            context['active_responsibilities'] = dept.vice_rector_responsibilities.filter(is_active=True).select_related('vice_rector')

        else:
            # Standard Employee
            context['my_department'] = user.department
            context['my_position'] = user.position

        return context


class AuditLogListView(RectorRequiredMixin, ListView):
    model = AuditLog
    template_name = 'core/audit_list.html'
    context_object_name = 'audit_logs'
    paginate_by = 20

    def get_queryset(self):
        qs = AuditLog.objects.select_related('actor')
        action_filter = self.request.GET.get('action', '').strip()
        if action_filter:
            qs = qs.filter(action=action_filter)
        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(target_repr__icontains=query)
                | Q(actor__username__icontains=query)
                | Q(actor__first_name__icontains=query)
                | Q(actor__last_name__icontains=query)
            )
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['actions'] = AuditLog.Actions.choices
        context['selected_action'] = self.request.GET.get('action', '')
        context['search_query'] = self.request.GET.get('q', '')
        return context


# ---------------------------------------------------------------------------
# Phase 5 — Notification Views
# ---------------------------------------------------------------------------

class NotificationListView(LoginRequiredMixin, ListView):
    template_name = 'core/notifications.html'
    context_object_name = 'notifications'
    paginate_by = 20

    def get_queryset(self):
        from core.models import Notification
        return Notification.objects.filter(
            recipient=self.request.user
        ).select_related('task').order_by('-created_at')


class NotificationMarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404
        from core.models import Notification
        notification = get_object_or_404(Notification, pk=pk)
        if notification.recipient != request.user:
            raise PermissionDenied(_('You cannot modify notifications belonging to other users.'))
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])
        if notification.link:
            return redirect(notification.link)
        return redirect('notifications')


class NotificationMarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        from core.models import Notification
        Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return redirect('notifications')


# ---------------------------------------------------------------------------
# Error Handling Views (400, 403, 404, 500)
# ---------------------------------------------------------------------------

def custom_400(request, exception=None):
    from django.shortcuts import render
    return render(request, '400.html', {'status_code': 400, 'exception': str(exception) if exception else ''}, status=400)


def custom_403(request, exception=None):
    from django.shortcuts import render
    return render(request, '403.html', {'status_code': 403, 'exception': str(exception) if exception else ''}, status=403)


def custom_404(request, exception=None):
    from django.shortcuts import render
    return render(request, '404.html', {'status_code': 404, 'exception': str(exception) if exception else ''}, status=404)


# ---------------------------------------------------------------------------
# Phase 15 — Health Checks & Observability Endpoints
# ---------------------------------------------------------------------------

class HealthCheckView(View):
    """
    Comprehensive system health diagnostic view:
    - HTML Dashboard for web browser requests (Accept: text/html)
    - JSON diagnostic response for monitoring probes, APIs, or ?format=json
    """
    def get(self, request):
        import sys
        import time
        import platform
        import shutil
        from django.db import connection
        from django.core.cache import cache
        from django.conf import settings
        from django.shortcuts import render
        from django.http import JsonResponse
        import django

        t0 = time.perf_counter()
        health = {
            'status': 'HEALTHY',
            'timestamp': timezone.now().isoformat(),
            'components': {},
            'python_version': sys.version.split()[0],
            'django_version': django.get_version(),
            'platform': platform.platform(),
        }

        # 1. Database Diagnostic
        db_start = time.perf_counter()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
            db_latency_ms = round((time.perf_counter() - db_start) * 1000, 2)
            db_status = 'UP' if row and row[0] == 1 else 'UNHEALTHY'
            health['components']['database'] = {
                'status': db_status,
                'latency_ms': db_latency_ms,
                'vendor': connection.vendor,
            }
            if db_status != 'UP':
                health['status'] = 'UNHEALTHY'
        except Exception as e:
            health['status'] = 'UNHEALTHY'
            health['components']['database'] = {
                'status': 'DOWN',
                'latency_ms': None,
                'error': str(e),
                'vendor': getattr(connection, 'vendor', 'unknown'),
            }

        # 2. Cache Diagnostic
        cache_start = time.perf_counter()
        try:
            cache.set('_health_ping', 'ok', timeout=10)
            val = cache.get('_health_ping')
            cache_latency_ms = round((time.perf_counter() - cache_start) * 1000, 2)
            cache_status = 'UP' if val == 'ok' else 'UNHEALTHY'
            health['components']['cache'] = {
                'status': cache_status,
                'latency_ms': cache_latency_ms,
                'backend': cache.__class__.__name__,
            }
            if cache_status != 'UP':
                health['status'] = 'DEGRADED' if health['status'] == 'HEALTHY' else health['status']
        except Exception as e:
            health['status'] = 'DEGRADED' if health['status'] == 'HEALTHY' else health['status']
            health['components']['cache'] = {
                'status': 'DEGRADED',
                'latency_ms': None,
                'error': str(e),
            }

        # 3. Disk & Storage Diagnostic
        try:
            disk_info = shutil.disk_usage(settings.BASE_DIR)
            disk_total_gb = round(disk_info.total / (1024 ** 3), 1)
            disk_used_gb = round(disk_info.used / (1024 ** 3), 1)
            disk_free_gb = round(disk_info.free / (1024 ** 3), 1)
            disk_percent = round((disk_info.used / disk_info.total) * 100, 1)
            health['components']['storage'] = {
                'status': 'UP' if disk_percent < 95 else 'WARNING',
                'total_gb': disk_total_gb,
                'used_gb': disk_used_gb,
                'free_gb': disk_free_gb,
                'percent': disk_percent,
            }
        except Exception as e:
            health['components']['storage'] = {
                'status': 'UNKNOWN',
                'error': str(e),
            }

        # 4. System Memory (if psutil available)
        try:
            import psutil
            mem = psutil.virtual_memory()
            health['components']['memory'] = {
                'status': 'UP' if mem.percent < 95 else 'WARNING',
                'total_gb': round(mem.total / (1024 ** 3), 1),
                'available_gb': round(mem.available / (1024 ** 3), 1),
                'percent': mem.percent,
            }
        except Exception:
            health['components']['memory'] = None

        total_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        health['response_time_ms'] = total_latency_ms

        status_code = 200 if health['status'] in ('HEALTHY', 'DEGRADED') else 503

        # Determine response format
        format_param = request.GET.get('format', '').lower().strip()
        accept_header = request.META.get('HTTP_ACCEPT', '')
        wants_html = format_param == 'html' or ('text/html' in accept_header and format_param != 'json')

        if wants_html:
            from accounts.models import User
            from tasks.models import Task
            from organization.models import Department
            from core.models import AuditLog

            try:
                user_count = User.objects.count()
                task_count = Task.objects.count()
                dept_count = Department.objects.count()
                audit_count = AuditLog.objects.count()
            except Exception:
                user_count = task_count = dept_count = audit_count = 0

            context = {
                'health': health,
                'status_code': status_code,
                'user_count': user_count,
                'task_count': task_count,
                'dept_count': dept_count,
                'audit_count': audit_count,
                'debug_mode': settings.DEBUG,
                'active_timezone': str(settings.TIME_ZONE),
            }
            return render(request, 'core/system_health.html', context, status=status_code)

        return JsonResponse(health, status=status_code)


class LivenessProbeView(View):
    """
    Kubernetes / Docker simple liveness probe.
    """
    def get(self, request):
        from django.http import HttpResponse
        return HttpResponse("OK", content_type="text/plain", status=200)


class ReadinessProbeView(View):
    """
    Kubernetes / Docker database readiness probe.
    """
    def get(self, request):
        from django.db import connection
        from django.http import HttpResponse
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return HttpResponse("READY", content_type="text/plain", status=200)
        except Exception:
            return HttpResponse("UNAVAILABLE", content_type="text/plain", status=503)


# ---------------------------------------------------------------------------
# Phase 15 — Unified Enterprise Global Search
# ---------------------------------------------------------------------------

class GlobalSearchView(LoginRequiredMixin, TemplateView):
    template_name = 'core/search_results.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get('q', '').strip()
        user = self.request.user
        context['search_query'] = query

        if query:
            # 1. Scoped Tasks
            from tasks.services import get_scoped_tasks
            from tasks.models import Task
            scoped_tasks = get_scoped_tasks(user, include_archived=True)
            context['tasks'] = scoped_tasks.filter(
                Q(title__icontains=query) | Q(task_number__icontains=query) | Q(description__icontains=query)
            ).select_related('responsible_department')[:15]

            # 2. University Requests / Applications
            from operations.models import UniversityRequest
            if user.is_superuser or user.is_rector or user.is_vice_rector:
                req_qs = UniversityRequest.objects.all()
            elif user.is_department_head and user.department:
                req_qs = UniversityRequest.objects.filter(Q(requester=user) | Q(department=user.department))
            else:
                req_qs = UniversityRequest.objects.filter(requester=user)
            context['requests'] = req_qs.filter(
                Q(subject__icontains=query) | Q(request_number__icontains=query)
            ).select_related('request_type', 'requester')[:15]

            # 3. Official Documents
            from operations.models import UniversityDocument
            context['documents'] = UniversityDocument.objects.filter(
                Q(title__icontains=query) | Q(doc_number__icontains=query) | Q(description__icontains=query)
            )[:15]

            # 4. Directory Employees
            context['users'] = User.objects.filter(
                Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query),
                is_active=True
            ).select_related('department', 'position')[:10]

            context['total_matches'] = (
                len(context.get('tasks', [])) + len(context.get('requests', [])) + len(context.get('documents', [])) + len(context.get('users', []))
            )
        else:
            context['tasks'] = []
            context['requests'] = []
            context['documents'] = []
            context['users'] = []
            context['total_matches'] = 0

        return context


def custom_500(request):
    try:
        from django.shortcuts import render as _render
        return _render(request, '500.html', {'status_code': 500}, status=500)
    except Exception:
        from django.http import HttpResponse
        return HttpResponse(
            '<html><body><h1>500 Internal Server Error</h1><p>An unexpected error occurred.</p></body></html>',
            status=500,
            content_type='text/html',
        )


class SetActiveYearView(LoginRequiredMixin, View):
    """
    Sets the active working year in the user's session.
    Preserves past year records and filters subsequent views accordingly.
    """
    def post(self, request, *args, **kwargs):
        year = request.POST.get('year')
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
        if year:
            try:
                year_int = int(year)
                if 2000 <= year_int <= 2100:
                    request.session['active_year'] = year_int
                    messages.success(
                        request,
                        _("Ishchi yil %(year)s ga muvaffaqiyatli o'zgartirildi.") % {'year': year_int}
                    )
            except (ValueError, TypeError):
                messages.error(request, _("Noto'g'ri yil kiritildi."))
        return redirect(next_url)

    def get(self, request, *args, **kwargs):
        year = request.GET.get('year')
        next_url = request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
        if year:
            try:
                year_int = int(year)
                if 2000 <= year_int <= 2100:
                    request.session['active_year'] = year_int
                    messages.success(
                        request,
                        _("Ishchi yil %(year)s ga muvaffaqiyatli o'zgartirildi.") % {'year': year_int}
                    )
            except (ValueError, TypeError):
                pass
        return redirect(next_url)


class CustomSetLanguageView(View):
    """
    Enhanced set_language view that correctly handles language switching
    between prefixed (/uz/...) and unprefixed (/...) URLs under i18n_patterns
    with prefix_default_language=False.
    Also persists preferred_language on the User model for authenticated users.
    """
    http_method_names = ['post', 'get']

    def post(self, request, *args, **kwargs):
        lang_code = request.POST.get('language') or request.GET.get('language')
        next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'

        supported_codes = dict(settings.LANGUAGES)
        if not lang_code or lang_code not in supported_codes:
            lang_code = settings.LANGUAGE_CODE

        # Translate next_url properly between languages
        redirect_url = self._translate_next_url(request, next_url, lang_code)

        response = HttpResponseRedirect(redirect_url)

        # 1. Update session
        if hasattr(request, 'session'):
            request.session[settings.LANGUAGE_COOKIE_NAME] = lang_code

        # 2. Update cookie
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            lang_code,
            max_age=getattr(settings, 'LANGUAGE_COOKIE_AGE', 365 * 24 * 60 * 60),
            path=getattr(settings, 'LANGUAGE_COOKIE_PATH', '/'),
            domain=getattr(settings, 'LANGUAGE_COOKIE_DOMAIN', None),
            secure=getattr(settings, 'LANGUAGE_COOKIE_SECURE', False),
            httponly=getattr(settings, 'LANGUAGE_COOKIE_HTTPONLY', False),
            samesite=getattr(settings, 'LANGUAGE_COOKIE_SAMESITE', 'Lax'),
        )

        # 3. Update user profile if authenticated
        if request.user.is_authenticated and hasattr(request.user, 'preferred_language'):
            if request.user.preferred_language != lang_code:
                request.user.preferred_language = lang_code
                request.user.save(update_fields=['preferred_language'])

        return response

    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)

    def _translate_next_url(self, request, next_url, target_language):
        if not next_url or not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            next_url = '/'

        parsed = urlsplit(next_url)
        path = unquote(parsed.path)

        # Identify source language prefix in path
        path_lang = translation.get_language_from_path(path)
        source_lang = path_lang or getattr(request, 'LANGUAGE_CODE', None) or settings.LANGUAGE_CODE

        match = None
        # Try resolving path under its source language
        with translation.override(source_lang):
            try:
                match = resolve(path)
            except Resolver404:
                pass

        # If not resolved, try all supported languages
        if not match:
            for code, _ in settings.LANGUAGES:
                with translation.override(code):
                    try:
                        match = resolve(path)
                        if match:
                            break
                    except Resolver404:
                        continue

        if match:
            view_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
            with translation.override(target_language):
                try:
                    new_path = reverse(view_name, args=match.args, kwargs=match.kwargs)
                    return urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))
                except NoReverseMatch:
                    pass

        # Fallback string manipulation if reverse fails
        if target_language == settings.LANGUAGE_CODE and path_lang:
            prefix = f"/{path_lang}/"
            if path.startswith(prefix):
                new_path = '/' + path[len(prefix):]
                return urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))
            elif path == f"/{path_lang}":
                return urlunsplit((parsed.scheme, parsed.netloc, '/', parsed.query, parsed.fragment))
        elif target_language != settings.LANGUAGE_CODE and not path_lang:
            new_path = f"/{target_language}" + (path if path.startswith('/') else f"/{path}")
            return urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))

        return next_url




