from datetime import time
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from automation.engine import (
    evaluate_rules_for_event,
    generate_due_recurring_tasks,
    process_escalation_policies,
    process_sla_checks,
)
from automation.models import (
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)
from core.models import AuditLog, log_audit


@transaction.atomic
def create_automation_rule(
    actor,
    name: str,
    trigger_event: str,
    action_type: str,
    description: str = '',
    conditions: dict = None,
    action_config: dict = None,
    priority_order: int = 10,
    is_active: bool = True,
) -> AutomationRule:
    """Creates a new automated workflow rule."""
    if not name.strip():
        raise ValidationError(_("Rule name is required."))

    rule = AutomationRule.objects.create(
        name=name.strip(),
        description=description.strip(),
        trigger_event=trigger_event,
        action_type=action_type,
        conditions=conditions or {},
        action_config=action_config or {},
        priority_order=priority_order,
        is_active=is_active,
        created_by=actor,
    )
    log_audit(
        actor=actor,
        action=AuditLog.Actions.RULE_CREATED,
        target_repr=f"Rule: {rule.name}",
        details={'trigger': trigger_event, 'action': action_type}
    )
    return rule


@transaction.atomic
def toggle_automation_rule(actor, rule: AutomationRule) -> bool:
    """Toggles rule active state."""
    rule.is_active = not rule.is_active
    rule.save(update_fields=['is_active', 'updated_at'])
    action = AuditLog.Actions.RULE_UPDATED if rule.is_active else AuditLog.Actions.RULE_DISABLED
    log_audit(
        actor=actor,
        action=action,
        target_repr=f"Rule: {rule.name}",
        details={'is_active': rule.is_active}
    )
    return rule.is_active


@transaction.atomic
def create_recurring_task_rule(
    actor,
    title: str,
    department,
    recurrence_type: str,
    description: str = '',
    priority: str = 'MEDIUM',
    day_of_week: int = None,
    day_of_month: int = None,
    time_of_day: str = '09:00:00',
    deadline_offset_days: int = 7,
    task_type=None,
    template=None,
    assignees=None,
    is_active: bool = True,
) -> RecurringTaskRule:
    """Creates a scheduled routine task generation rule."""
    if not title.strip():
        raise ValidationError(_("Task title is required."))

    rule = RecurringTaskRule.objects.create(
        title=title.strip(),
        description=description.strip(),
        responsible_department=department,
        recurrence_type=recurrence_type,
        priority=priority,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        time_of_day=time_of_day,
        deadline_offset_days=deadline_offset_days,
        task_type=task_type,
        template=template,
        is_active=is_active,
        created_by=actor,
    )
    if assignees:
        rule.assignees.set(assignees)

    log_audit(
        actor=actor,
        action=AuditLog.Actions.RULE_CREATED,
        target_repr=f"Recurring: {rule.title}",
        details={'dept': department.name, 'recurrence': recurrence_type}
    )
    return rule


def run_full_automation_cycle(now=None):
    """
    Executes a complete scheduled pass: recurring task generation, SLA checks, and escalations.
    """
    if now is None:
        now = timezone.now()

    created_tasks = generate_due_recurring_tasks(now=now)
    sla_alerts = process_sla_checks(now=now)
    escalations = process_escalation_policies(now=now)

    return {
        'tasks_generated': len(created_tasks),
        'sla_alerts_triggered': sla_alerts,
        'escalations_dispatched': escalations,
        'timestamp': now.isoformat(),
    }
