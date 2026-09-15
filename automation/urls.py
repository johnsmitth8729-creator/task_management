from django.urls import path
from automation import views

app_name = 'automation'

urlpatterns = [
    # Dashboard & Cycle Runner
    path('', views.AutomationDashboardView.as_view(), name='dashboard'),
    path('run-cycle/', views.RunAutomationCycleNowView.as_view(), name='run_cycle'),

    # Rules
    path('rules/', views.RuleListView.as_view(), name='rule_list'),
    path('rules/create/', views.RuleCreateView.as_view(), name='rule_create'),
    path('rules/<uuid:pk>/edit/', views.RuleUpdateView.as_view(), name='rule_edit'),
    path('rules/<uuid:pk>/toggle/', views.RuleToggleView.as_view(), name='rule_toggle'),

    # SLA Policies
    path('sla/', views.SLAPolicyListView.as_view(), name='sla_list'),
    path('sla/create/', views.SLAPolicyCreateView.as_view(), name='sla_create'),
    path('sla/<uuid:pk>/edit/', views.SLAPolicyUpdateView.as_view(), name='sla_edit'),

    # Escalation Policies
    path('escalation/', views.EscalationPolicyListView.as_view(), name='escalation_list'),
    path('escalation/create/', views.EscalationPolicyCreateView.as_view(), name='escalation_create'),
    path('escalation/<uuid:pk>/edit/', views.EscalationPolicyUpdateView.as_view(), name='escalation_edit'),

    # Recurring Tasks
    path('recurring/', views.RecurringTaskListView.as_view(), name='recurring_list'),
    path('recurring/create/', views.RecurringTaskCreateView.as_view(), name='recurring_create'),
    path('recurring/<uuid:pk>/edit/', views.RecurringTaskUpdateView.as_view(), name='recurring_edit'),

    # Execution History
    path('history/', views.ExecutionHistoryView.as_view(), name='execution_history'),
]
