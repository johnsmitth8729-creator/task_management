from django.urls import path

from .views import AuditLogListView, DashboardView, HomeRedirectView

urlpatterns = [
    path('', HomeRedirectView.as_view(), name='home'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('audit/', AuditLogListView.as_view(), name='audit_list'),
]
