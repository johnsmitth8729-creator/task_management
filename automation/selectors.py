from datetime import timedelta
from django.db.models import Count, Q
from django.utils import timezone

from automation.models import (
    AutomationExecution,
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)
from tasks.models import Task


def get_automation_metrics(user=None):
    """
    Computes aggregate metrics for the automation dashboard.
    """
    total_rules = AutomationRule.objects.count()
    active_rules = AutomationRule.objects.filter(is_active=True).count()
    total_recurring = RecurringTaskRule.objects.count()
    active_recurring = RecurringTaskRule.objects.filter(is_active=True).count()
    total_sla_policies = SLAPolicy.objects.count()
    active_sla_policies = SLAPolicy.objects.filter(is_active=True).count()
    total_escalations = EscalationPolicy.objects.count()
    active_escalations = EscalationPolicy.objects.filter(is_active=True).count()

    total_executions = AutomationExecution.objects.count()
    successful_executions = AutomationExecution.objects.filter(status=AutomationExecution.Status.SUCCESS).count()
    failed_executions = AutomationExecution.objects.filter(status=AutomationExecution.Status.FAILED).count()

    success_rate = 100.0
    if total_executions > 0:
        success_rate = round((successful_executions / total_executions) * 100, 1)

    # SLA metrics across active tasks
    open_tasks = Task.objects.filter(
        status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]
    )
    sla_breached_count = 0
    sla_warning_count = 0
    now = timezone.now()

    for task in open_tasks:
        sla = get_sla_status_for_task(task, now=now)
        if sla['status'] == 'BREACHED':
            sla_breached_count += 1
        elif sla['status'] == 'WARNING':
            sla_warning_count += 1

    return {
        'total_rules': total_rules,
        'active_rules': active_rules,
        'total_recurring': total_recurring,
        'active_recurring': active_recurring,
        'total_sla_policies': total_sla_policies,
        'active_sla_policies': active_sla_policies,
        'total_escalations': total_escalations,
        'active_escalations': active_escalations,
        'total_executions': total_executions,
        'successful_executions': successful_executions,
        'failed_executions': failed_executions,
        'success_rate': success_rate,
        'sla_breached_count': sla_breached_count,
        'sla_warning_count': sla_warning_count,
    }


def get_sla_status_for_task(task: Task, now=None):
    """
    Determines real-time SLA status and metrics for a given task.
    """
    if now is None:
        now = timezone.now()

    # Match policy by task priority (handle URGENT <-> CRITICAL compatibility)
    target_p = task.priority
    if target_p == 'URGENT':
        target_p = 'CRITICAL'
    policy = SLAPolicy.objects.filter(Q(priority=task.priority) | Q(priority=target_p), is_active=True).first()
    if not policy:
        return {
            'policy': None,
            'status': 'NO_POLICY',
            'label': 'No SLA Policy',
            'badge_class': 'bg-secondary',
            'elapsed_hours': 0,
            'max_hours': 0,
            'percent_elapsed': 0,
            'is_breached': False,
            'is_warning': False,
        }

    # Resolution SLA calculation from task creation
    start_time = task.created_at
    end_time = task.completed_at if task.completed_at else now
    elapsed_seconds = (end_time - start_time).total_seconds()
    elapsed_hours = max(0, round(elapsed_seconds / 3600.0, 1))

    max_hours = float(policy.resolution_hours)
    percent_elapsed = min(100.0, round((elapsed_hours / max_hours) * 100, 1)) if max_hours > 0 else 0

    if task.status == Task.Status.COMPLETED:
        if elapsed_hours <= max_hours:
            return {
                'policy': policy,
                'status': 'RESOLVED_ON_TIME',
                'label': 'Met SLA Target',
                'badge_class': 'bg-success',
                'elapsed_hours': elapsed_hours,
                'max_hours': max_hours,
                'percent_elapsed': percent_elapsed,
                'is_breached': False,
                'is_warning': False,
            }
        else:
            return {
                'policy': policy,
                'status': 'RESOLVED_BREACHED',
                'label': 'Resolved (SLA Breached)',
                'badge_class': 'bg-danger',
                'elapsed_hours': elapsed_hours,
                'max_hours': max_hours,
                'percent_elapsed': percent_elapsed,
                'is_breached': True,
                'is_warning': False,
            }

    # Open task
    if elapsed_hours > max_hours:
        return {
            'policy': policy,
            'status': 'BREACHED',
            'label': 'SLA Breached',
            'badge_class': 'bg-danger',
            'elapsed_hours': elapsed_hours,
            'max_hours': max_hours,
            'percent_elapsed': percent_elapsed,
            'is_breached': True,
            'is_warning': False,
        }
    elif percent_elapsed >= policy.warning_threshold_percent:
        return {
            'policy': policy,
            'status': 'WARNING',
            'label': 'SLA Warning',
            'badge_class': 'bg-warning text-dark',
            'elapsed_hours': elapsed_hours,
            'max_hours': max_hours,
            'percent_elapsed': percent_elapsed,
            'is_breached': False,
            'is_warning': True,
        }
    else:
        return {
            'policy': policy,
            'status': 'ON_TRACK',
            'label': 'On Track',
            'badge_class': 'bg-success',
            'elapsed_hours': elapsed_hours,
            'max_hours': max_hours,
            'percent_elapsed': percent_elapsed,
            'is_breached': False,
            'is_warning': False,
        }


def get_scoped_recurring_tasks(user):
    """
    Returns recurring task rules scoped to the user's authority.
    """
    if not user.is_authenticated:
        return RecurringTaskRule.objects.none()
    if user.is_superuser or getattr(user, 'is_rector', False):
        return RecurringTaskRule.objects.all().select_related('responsible_department', 'task_type', 'created_by')
    if getattr(user, 'is_vice_rector', False):
        scoped_depts = user.get_scoped_departments()
        return RecurringTaskRule.objects.filter(responsible_department__in=scoped_depts).select_related('responsible_department', 'task_type', 'created_by')
    if getattr(user, 'is_department_head', False):
        return RecurringTaskRule.objects.filter(responsible_department_id=user.department_id).select_related('responsible_department', 'task_type', 'created_by')
    return RecurringTaskRule.objects.none()
