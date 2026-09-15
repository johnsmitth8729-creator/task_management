from django.urls import path

from .views import (
    AuditLogListView,
    DashboardView,
    GlobalSearchView,
    HealthCheckView,
    LandingPageView,
    LivenessProbeView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    ReadinessProbeView,
    SetActiveYearView,
    custom_400,
    custom_403,
    custom_404,
    custom_500,
)

urlpatterns = [
    path('', LandingPageView.as_view(), name='home'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('set-year/', SetActiveYearView.as_view(), name='set_active_year'),
    path('audit/', AuditLogListView.as_view(), name='audit_list'),
    path('notifications/', NotificationListView.as_view(), name='notifications'),
    path('notifications/<uuid:pk>/read/', NotificationMarkReadView.as_view(), name='notification_mark_read'),
    path('notifications/mark-all-read/', NotificationMarkAllReadView.as_view(), name='notification_mark_all_read'),
    # Phase 15 — Global Search & System Health Probes
    path('search/', GlobalSearchView.as_view(), name='global_search'),
    path('health/', HealthCheckView.as_view(), name='health_check'),
    path('health/live/', LivenessProbeView.as_view(), name='health_live'),
    path('health/ready/', ReadinessProbeView.as_view(), name='health_ready'),
    # Error page previews
    path('error/400/', custom_400, name='error_400'),
    path('error/403/', custom_403, name='error_403'),
    path('error/404/', custom_404, name='error_404'),
    path('error/500/', custom_500, name='error_500'),
]


