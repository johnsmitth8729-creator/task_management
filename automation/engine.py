import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import Role, User
from automation.models import (
    AutomationExecution,
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)
from core.models import AuditLog, Notification, log_audit
from tasks.models import Task, TaskAssignment, TaskApproval, TaskSubmission

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Event-Driven Automation Rule Engine
# ---------------------------------------------------------------------------

def match_conditions(conditions: dict, target_obj) -> bool:
    """
    Evaluates JSON conditions against object attributes.
    Supports nested field matching, e.g. {"priority": "HIGH", "department_code": "IT"}.
    """
    if not conditions:
        return True

    for key, expected_val in conditions.items():
        if key == 'priority':
            actual_val = getattr(target_obj, 'priority', None)
            if actual_val != expected_val:
                return False
        elif key == 'department_code':
            dept = getattr(target_obj, 'responsible_department', None)
            if not dept or dept.code != expected_val:
                return False
        elif key == 'status':
            actual_val = getattr(target_obj, 'status', None)
            if actual_val != expected_val:
                return False
        elif key == 'is_overdue':
            if hasattr(target_obj, 'is_overdue'):
                if target_obj.is_overdue != expected_val:
                    return False
    return True


def execute_action(rule: AutomationRule, target_obj, user=None) -> str:
    """
    Executes the configured action on the target entity.
    """
    action_type = rule.action_type
    config = rule.action_config or {}
    msg_template = config.get('message', f"Automated Action triggered by {rule.name}")

    if action_type == AutomationRule.ActionType.SEND_NOTIFICATION:
        recipients = []
        if isinstance(target_obj, Task):
            recipients = [a.user for a in target_obj.assignments.all()]
            if target_obj.creator and target_obj.creator not in recipients:
                recipients.append(target_obj.creator)
        for recipient in recipients:
            Notification.objects.create(
                recipient=recipient,
                notification_type=Notification.NotificationType.GENERAL,
                title=f"[Rule: {rule.name}] Notification",
                message=msg_template,
                task=target_obj if isinstance(target_obj, Task) else None,
            )
        return f"Dispatched notifications to {len(recipients)} users."

    elif action_type == AutomationRule.ActionType.AUTO_ASSIGN:
        user_id = config.get('user_id')
        if user_id and isinstance(target_obj, Task):
            try:
                target_user = User.objects.get(id=user_id)
                TaskAssignment.objects.get_or_create(
                    task=target_obj,
                    user=target_user,
                    defaults={'assigned_by': user or target_obj.creator}
                )
                return f"Auto-assigned task to {target_user.display_name}."
            except User.DoesNotExist:
                return "Target user not found for auto-assignment."

    elif action_type == AutomationRule.ActionType.ESCALATE_SUPERVISOR:
        if isinstance(target_obj, Task) and target_obj.responsible_department:
            head = target_obj.responsible_department.head
            if head:
                Notification.objects.create(
                    recipient=head,
                    notification_type=Notification.NotificationType.GENERAL,
                    title=f"[ESCALATION: Dept Head] {target_obj.title}",
                    message=f"{target_obj.title}: {msg_template}",
                    task=target_obj,
                )
                return f"Escalated to Department Head: {head.display_name}."
        return "No Department Head found to escalate."

    elif action_type == AutomationRule.ActionType.ESCALATE_VICE_RECTOR:
        if isinstance(target_obj, Task) and target_obj.responsible_department:
            vice_rectors = User.objects.filter(
                department_responsibilities__department=target_obj.responsible_department,
                department_responsibilities__is_active=True
            ).distinct()
            for vr in vice_rectors:
                Notification.objects.create(
                    recipient=vr,
                    notification_type=Notification.NotificationType.GENERAL,
                    title=f"[ESCALATION: Vice Rector] {target_obj.title}",
                    message=f"{target_obj.title}: {msg_template}",
                    task=target_obj,
                )
            return f"Escalated to {vice_rectors.count()} Vice Rector(s)."
        return "No Vice Rector found."

    elif action_type == AutomationRule.ActionType.ESCALATE_RECTOR:
        rectors = User.objects.filter(roles__code=Role.Codes.RECTOR).distinct()
        for rector in rectors:
            Notification.objects.create(
                recipient=rector,
                notification_type=Notification.NotificationType.GENERAL,
                title=f"[CRITICAL ESCALATION: Rector] {target_obj}",
                message=f"{target_obj}: {msg_template}",
                task=target_obj if isinstance(target_obj, Task) else None,
            )
        return f"Escalated to {rectors.count()} Rector(s)."

    elif action_type == AutomationRule.ActionType.SET_PRIORITY:
        new_priority = config.get('target_priority', Task.Priority.CRITICAL)
        if isinstance(target_obj, Task):
            target_obj.priority = new_priority
            target_obj.save(update_fields=['priority'])
            return f"Updated task priority to {new_priority}."

    return "No matching action handler."


def evaluate_rules_for_event(trigger_event: str, target_obj, user=None):
    """
    Evaluates all active rules matching trigger_event against target_obj.
    """
    rules = AutomationRule.objects.filter(trigger_event=trigger_event, is_active=True).order_by('priority_order')
    executed = []
    for rule in rules:
        try:
            if match_conditions(rule.conditions, target_obj):
                summary = execute_action(rule, target_obj, user=user)
                exec_record = AutomationExecution.objects.create(
                    rule=rule,
                    trigger_event=trigger_event,
                    target_repr=str(target_obj),
                    target_id=str(getattr(target_obj, 'id', '')),
                    status=AutomationExecution.Status.SUCCESS,
                    result_summary=summary,
                )
                executed.append(exec_record)
                log_audit(
                    actor=user,
                    action=AuditLog.Actions.AUTOMATION_EXECUTED,
                    target_repr=f"Rule: {rule.name}",
                    details={'trigger': trigger_event, 'target': str(target_obj), 'summary': summary}
                )
        except Exception as e:
            logger.exception(f"Error executing rule {rule.id}: {e}")
            exec_record = AutomationExecution.objects.create(
                rule=rule,
                trigger_event=trigger_event,
                target_repr=str(target_obj),
                target_id=str(getattr(target_obj, 'id', '')),
                status=AutomationExecution.Status.FAILED,
                result_summary="Execution failed with exception.",
                error_message=str(e),
            )
            executed.append(exec_record)
            log_audit(
                actor=user,
                action=AuditLog.Actions.AUTOMATION_FAILED,
                target_repr=f"Rule: {rule.name}",
                details={'trigger': trigger_event, 'error': str(e)}
            )
    return executed


# ---------------------------------------------------------------------------
# 2. SLA Check Engine
# ---------------------------------------------------------------------------

def process_sla_checks(now=None):
    """
    Evaluates all open tasks against SLAPolicy and triggers SLA breach/warning alerts.
    """
    if now is None:
        now = timezone.now()

    open_tasks = Task.objects.filter(
        status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]
    ).select_related('responsible_department', 'creator')

    policies = {p.priority: p for p in SLAPolicy.objects.filter(is_active=True)}
    alerts_triggered = 0

    for task in open_tasks:
        policy = policies.get(task.priority)
        if not policy:
            continue

        elapsed_hours = (now - task.created_at).total_seconds() / 3600.0
        max_hours = float(policy.resolution_hours)

        if elapsed_hours > max_hours:
            # Check if breach was already logged today for this task
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            already_notified = Notification.objects.filter(
                task=task,
                title__icontains="[SLA BREACHED]",
                created_at__gte=today_start
            ).exists()

            if not already_notified:
                if task.responsible_department and task.responsible_department.head:
                    Notification.objects.create(
                        recipient=task.responsible_department.head,
                        notification_type=Notification.NotificationType.GENERAL,
                        title=f"[SLA BREACHED] {task.title}",
                        message=f"Task '{task.title}' has exceeded its {policy.resolution_hours}h SLA limit.",
                        task=task,
                    )
                log_audit(
                    actor=None,
                    action=AuditLog.Actions.SLA_BREACHED,
                    target_repr=f"Task: {task.title}",
                    details={'priority': task.priority, 'elapsed_hours': round(elapsed_hours, 1), 'sla_hours': policy.resolution_hours}
                )
                alerts_triggered += 1

    return alerts_triggered


# ---------------------------------------------------------------------------
# 3. Escalation Engine
# ---------------------------------------------------------------------------

def process_escalation_policies(now=None):
    """
    Evaluates EscalationPolicy definitions against overdue deadlines and approval queues.
    """
    if now is None:
        now = timezone.now()

    policies = EscalationPolicy.objects.filter(is_active=True).order_by('hours_threshold')
    escalations_count = 0

    for policy in policies:
        if policy.trigger_type == EscalationPolicy.TriggerType.DEADLINE_PASSED:
            # Tasks overdue by at least policy.hours_threshold hours
            threshold_time = now - timedelta(hours=policy.hours_threshold)
            overdue_tasks = Task.objects.filter(
                status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS],
                deadline__lt=threshold_time.date()
            ).select_related('responsible_department')

            for task in overdue_tasks:
                if dispatch_escalation(policy, task, now):
                    escalations_count += 1

        elif policy.trigger_type == EscalationPolicy.TriggerType.APPROVAL_STAGE_1_OVERDUE:
            # Pending Stage 1 Submissions older than policy.hours_threshold hours
            threshold_time = now - timedelta(hours=policy.hours_threshold)
            pending_submissions = TaskSubmission.objects.filter(
                status=TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL,
                created_at__lte=threshold_time
            ).select_related('assignment__task__responsible_department')

            for sub in pending_submissions:
                if dispatch_escalation(policy, sub.assignment.task, now, context_type="Submission Stage 1"):
                    escalations_count += 1

    return escalations_count


def dispatch_escalation(policy: EscalationPolicy, task: Task, now, context_type="Task") -> bool:
    """
    Dispatches escalation notification to the appropriate target role with deduplication.
    """
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    already_sent = Notification.objects.filter(
        task=task,
        title__icontains=f"[{policy.name}]",
        created_at__gte=today_start
    ).exists()

    if already_sent:
        return False

    recipients = []
    if policy.escalate_to_role == EscalationPolicy.EscalateToRole.SUPERVISOR:
        if task.responsible_department and task.responsible_department.head:
            recipients.append(task.responsible_department.head)
    elif policy.escalate_to_role == EscalationPolicy.EscalateToRole.DEPARTMENT_HEAD:
        if task.responsible_department and task.responsible_department.head:
            recipients.append(task.responsible_department.head)
    elif policy.escalate_to_role == EscalationPolicy.EscalateToRole.VICE_RECTOR:
        if task.responsible_department:
            vrs = User.objects.filter(
                department_responsibilities__department=task.responsible_department,
                department_responsibilities__is_active=True
            )
            recipients.extend(list(vrs))
    elif policy.escalate_to_role == EscalationPolicy.EscalateToRole.RECTOR:
        recipients = list(User.objects.filter(roles__code=Role.Codes.RECTOR))
    elif policy.escalate_to_role == EscalationPolicy.EscalateToRole.SUPERADMIN:
        recipients = list(User.objects.filter(is_superuser=True))

    for user in recipients:
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.GENERAL,
            title=f"[{policy.name}] Escalation Alert",
            message=f"{context_type} '{task.title}' reached escalation threshold ({policy.hours_threshold}h).",
            task=task,
        )

    log_audit(
        actor=None,
        action=AuditLog.Actions.ESCALATION_TRIGGERED,
        target_repr=f"Task: {task.title}",
        details={'policy': policy.name, 'role': policy.escalate_to_role, 'recipients_count': len(recipients)}
    )
    return bool(recipients)


# ---------------------------------------------------------------------------
# 4. Recurring Task Generator
# ---------------------------------------------------------------------------

@transaction.atomic
def generate_due_recurring_tasks(now=None):
    """
    Idempotent generator creating tasks from active RecurringTaskRule schedules.
    """
    if now is None:
        now = timezone.now()

    today_date = now.date()
    rules = RecurringTaskRule.objects.filter(is_active=True).select_related(
        'responsible_department', 'task_type', 'template', 'created_by'
    )
    created_tasks = []

    for rule in rules:
        should_run = False

        if not rule.last_run_at:
            should_run = True
        else:
            last_run_date = rule.last_run_at.date()
            if rule.recurrence_type == RecurringTaskRule.RecurrenceType.DAILY:
                if last_run_date < today_date:
                    should_run = True
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.WEEKLY:
                if (today_date - last_run_date).days >= 7:
                    should_run = True
                elif rule.day_of_week is not None and today_date.weekday() == rule.day_of_week and last_run_date < today_date:
                    should_run = True
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.MONTHLY:
                if (today_date - last_run_date).days >= 28 and today_date.day == (rule.day_of_month or 1):
                    should_run = True
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.QUARTERLY:
                if (today_date - last_run_date).days >= 85:
                    should_run = True
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.YEARLY:
                if (today_date - last_run_date).days >= 360:
                    should_run = True
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.CUSTOM:
                if rule.next_run_at and now >= rule.next_run_at:
                    should_run = True

        if should_run:
            deadline = today_date + timedelta(days=rule.deadline_offset_days)
            task = Task.objects.create(
                title=rule.title,
                description=rule.description,
                responsible_department=rule.responsible_department,
                priority=rule.priority,
                task_type=rule.task_type,
                creator=rule.created_by,
                status=Task.Status.CREATED,
                deadline=deadline,
            )

            # Assign default assignees
            assignees = rule.assignees.all()
            for user in assignees:
                TaskAssignment.objects.create(
                    task=task,
                    user=user,
                    assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
                    assigned_by=rule.created_by or user,
                )
            if assignees.exists():
                task.status = Task.Status.ASSIGNED
                task.save(update_fields=['status'])

            # Update recurrence timestamps
            rule.last_run_at = now
            if rule.recurrence_type == RecurringTaskRule.RecurrenceType.DAILY:
                rule.next_run_at = now + timedelta(days=1)
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.WEEKLY:
                rule.next_run_at = now + timedelta(days=7)
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.MONTHLY:
                rule.next_run_at = now + timedelta(days=30)
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.QUARTERLY:
                rule.next_run_at = now + timedelta(days=90)
            elif rule.recurrence_type == RecurringTaskRule.RecurrenceType.YEARLY:
                rule.next_run_at = now + timedelta(days=365)
            rule.save(update_fields=['last_run_at', 'next_run_at'])

            log_audit(
                actor=rule.created_by,
                action=AuditLog.Actions.RECURRING_TASK_GENERATED,
                target_repr=f"Task: {task.title}",
                details={'rule_id': str(rule.id), 'recurrence': rule.recurrence_type, 'deadline': str(deadline)}
            )
            created_tasks.append(task)

    return created_tasks
