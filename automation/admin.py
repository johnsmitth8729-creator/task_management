from django.contrib import admin
from automation.models import (
    AutomationExecution,
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)


@admin.register(SLAPolicy)
class SLAPolicyAdmin(admin.ModelAdmin):
    list_display = ['priority', 'name', 'first_response_hours', 'resolution_hours', 'warning_threshold_percent', 'is_active']
    list_filter = ['is_active', 'priority']


@admin.register(EscalationPolicy)
class EscalationPolicyAdmin(admin.ModelAdmin):
    list_display = ['name', 'trigger_type', 'hours_threshold', 'escalate_to_role', 'is_active']
    list_filter = ['trigger_type', 'escalate_to_role', 'is_active']


@admin.register(RecurringTaskRule)
class RecurringTaskRuleAdmin(admin.ModelAdmin):
    list_display = ['title', 'responsible_department', 'recurrence_type', 'priority', 'last_run_at', 'is_active']
    list_filter = ['recurrence_type', 'priority', 'is_active', 'responsible_department']
    search_fields = ['title', 'description']


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'trigger_event', 'action_type', 'priority_order', 'is_active']
    list_filter = ['trigger_event', 'action_type', 'is_active']
    search_fields = ['name', 'description']


@admin.register(AutomationExecution)
class AutomationExecutionAdmin(admin.ModelAdmin):
    list_display = ['executed_at', 'status', 'trigger_event', 'target_repr', 'rule']
    list_filter = ['status', 'trigger_event']
    search_fields = ['target_repr', 'result_summary', 'error_message']
    readonly_fields = ['id', 'rule', 'trigger_event', 'target_repr', 'target_id', 'status', 'result_summary', 'error_message', 'executed_at']
