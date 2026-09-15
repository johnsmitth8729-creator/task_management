from django.urls import path
from analytics import views

app_name = 'analytics'

urlpatterns = [
    # Dashboards
    path('', views.AnalyticsIndexRedirectView.as_view(), name='index'),
    path('executive/', views.ExecutiveAnalyticsView.as_view(), name='executive_dashboard'),
    path('departments/', views.DepartmentAnalyticsView.as_view(), name='department_analytics'),
    path('personal/', views.EmployeePersonalAnalyticsView.as_view(), name='personal_analytics'),
    path('hr/', views.HRAnalyticsView.as_view(), name='hr_analytics'),
    path('payroll/', views.PayrollAnalyticsView.as_view(), name='payroll_analytics'),
    path('signatures/', views.SignatureAnalyticsView.as_view(), name='signature_analytics'),
    path('audit/', views.AuditSecurityAnalyticsView.as_view(), name='audit_analytics'),

    # Report Center & Exports
    path('reports/', views.ReportCenterView.as_view(), name='report_center'),
    path('reports/export/', views.ReportExportView.as_view(), name='report_export'),

    # APIs for interactive frontend charts
    path('api/tasks/', views.api_task_analytics, name='api_tasks'),
    path('api/trends/', views.api_trend_analytics, name='api_trends'),
    path('api/departments/', views.api_department_analytics, name='api_departments'),
]
