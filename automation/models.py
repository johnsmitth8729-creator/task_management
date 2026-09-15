import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from organization.models import Department
from tasks.models import Task, TaskTemplate, TaskType


class SLAPolicy(models.Model):
    """
    Defines official service level agreements by task priority.
    """
    class Priority(models.TextChoices):
        CRITICAL = 'CRITICAL', _('Critical')
        HIGH = 'HIGH', _('High')
        MEDIUM = 'MEDIUM', _('Medium')
        LOW = 'LOW', _('Low')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('policy name'), max_length=120)
    priority = models.CharField(_('priority level'), max_length=20, choices=Priority.choices, unique=True)
    first_response_hours = models.PositiveIntegerField(
        _('first response deadline (hours)'),
        default=24,
        help_text=_('Maximum hours allowed before task assignment is accepted or work starts.')
    )
    resolution_hours = models.PositiveIntegerField(
        _('resolution deadline (hours)'),
        default=72,
        help_text=_('Maximum hours allowed before task completion and final approval.')
    )
    warning_threshold_percent = models.PositiveIntegerField(
        _('warning threshold (%)'),
        default=80,
        help_text=_('Percentage of resolution time elapsed before SLA warning is triggered.')
    )
    is_active = models.BooleanField(_('is active'), default=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('SLA policy')
        verbose_name_plural = _('SLA policies')
        ordering = ['priority']

    def __str__(self):
        return f"{self.get_priority_display()} SLA ({self.resolution_hours}h)"


class EscalationPolicy(models.Model):
    """
    Multi-tier escalation rules for delayed deadlines and pending approvals.
    """
    class TriggerType(models.TextChoices):
        DEADLINE_APPROACHING = 'DEADLINE_APPROACHING', _('Deadline Approaching')
        DEADLINE_PASSED = 'DEADLINE_PASSED', _('Deadline Passed / Overdue')
        APPROVAL_STAGE_1_OVERDUE = 'APPROVAL_STAGE_1_OVERDUE', _('Stage 1 Approval Overdue')
        APPROVAL_STAGE_2_OVERDUE = 'APPROVAL_STAGE_2_OVERDUE', _('Stage 2 Final Approval Overdue')

    class EscalateToRole(models.TextChoices):
        SUPERVISOR = 'SUPERVISOR', _('Direct Supervisor / Lead')
        DEPARTMENT_HEAD = 'DEPARTMENT_HEAD', _('Department Head')
        VICE_RECTOR = 'VICE_RECTOR', _('Supervising Vice Rector')
        RECTOR = 'RECTOR', _('University Rector')
        SUPERADMIN = 'SUPERADMIN', _('Technical Superadmin')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('escalation policy name'), max_length=150)
    trigger_type = models.CharField(_('trigger type'), max_length=40, choices=TriggerType.choices)
    hours_threshold = models.IntegerField(
        _('hours threshold'),
        default=24,
        help_text=_('Hours relative to deadline or submission (e.g., -24 for 24h prior, 24 for 24h overdue, 48 for 48h overdue).')
    )
    escalate_to_role = models.CharField(_('escalate to role'), max_length=40, choices=EscalateToRole.choices)
    send_email = models.BooleanField(_('send email notification'), default=True)
    send_telegram = models.BooleanField(_('send telegram notification'), default=False)
    is_active = models.BooleanField(_('is active'), default=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('escalation policy')
        verbose_name_plural = _('escalation policies')
        ordering = ['trigger_type', 'hours_threshold']

    def __str__(self):
        return f"{self.name} -> {self.get_escalate_to_role_display()} ({self.hours_threshold}h)"


class RecurringTaskRule(models.Model):
    """
    Automated generation rule for routine university tasks.
    """
    class RecurrenceType(models.TextChoices):
        DAILY = 'DAILY', _('Daily')
        WEEKLY = 'WEEKLY', _('Weekly')
        MONTHLY = 'MONTHLY', _('Monthly')
        QUARTERLY = 'QUARTERLY', _('Quarterly')
        YEARLY = 'YEARLY', _('Yearly')
        CUSTOM = 'CUSTOM', _('Custom Interval')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(_('recurring task title'), max_length=255)
    description = models.TextField(_('task description'), blank=True)
    responsible_department = models.ForeignKey(
        Department,
        verbose_name=_('responsible department'),
        on_delete=models.CASCADE,
        related_name='recurring_task_rules'
    )
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('default assignees'),
        blank=True,
        related_name='recurring_task_assignments'
    )
    priority = models.CharField(
        _('priority'),
        max_length=20,
        choices=Task.Priority.choices,
        default=Task.Priority.MEDIUM
    )
    task_type = models.ForeignKey(
        TaskType,
        verbose_name=_('task type'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_task_rules'
    )
    template = models.ForeignKey(
        TaskTemplate,
        verbose_name=_('task template'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_task_rules'
    )
    recurrence_type = models.CharField(
        _('recurrence interval'),
        max_length=20,
        choices=RecurrenceType.choices,
        default=RecurrenceType.WEEKLY
    )
    day_of_week = models.IntegerField(
        _('day of week'),
        null=True,
        blank=True,
        help_text=_('0=Monday, 6=Sunday (for Weekly recurrence)')
    )
    day_of_month = models.IntegerField(
        _('day of month'),
        null=True,
        blank=True,
        help_text=_('1-31 (for Monthly/Quarterly recurrence)')
    )
    time_of_day = models.TimeField(_('generation time of day'), default='09:00:00')
    deadline_offset_days = models.PositiveIntegerField(
        _('deadline offset (days)'),
        default=7,
        help_text=_('Number of days from generation date until the task deadline.')
    )
    is_active = models.BooleanField(_('is active'), default=True)
    last_run_at = models.DateTimeField(_('last executed at'), null=True, blank=True)
    next_run_at = models.DateTimeField(_('next scheduled run'), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_recurring_task_rules'
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('recurring task rule')
        verbose_name_plural = _('recurring task rules')
        ordering = ['title']

    def __str__(self):
        return f"{self.title} ({self.get_recurrence_type_display()} - {self.responsible_department.name})"


class AutomationRule(models.Model):
    """
    Configurable event-driven rule engine for reactive task & workflow actions.
    """
    class TriggerEvent(models.TextChoices):
        TASK_CREATED = 'TASK_CREATED', _('Task Created')
        DEADLINE_APPROACHING = 'DEADLINE_APPROACHING', _('Deadline Approaching (<=24h)')
        TASK_OVERDUE = 'TASK_OVERDUE', _('Task Overdue')
        SUBMISSION_CREATED = 'SUBMISSION_CREATED', _('Deliverable Submitted')
        FIRST_APPROVAL_OVERDUE = 'FIRST_APPROVAL_OVERDUE', _('First Approval Pending > 24h')
        TASK_COMPLETED = 'TASK_COMPLETED', _('Task Completed (Final Approved)')
        SIGNATURE_CREATED = 'SIGNATURE_CREATED', _('Task Cryptographically Signed')

    class ActionType(models.TextChoices):
        SEND_NOTIFICATION = 'SEND_NOTIFICATION', _('Send Push & System Notification')
        ESCALATE_SUPERVISOR = 'ESCALATE_SUPERVISOR', _('Escalate to Department Head')
        ESCALATE_VICE_RECTOR = 'ESCALATE_VICE_RECTOR', _('Escalate to Supervising Vice Rector')
        ESCALATE_RECTOR = 'ESCALATE_RECTOR', _('Escalate to Rector')
        SET_PRIORITY = 'SET_PRIORITY', _('Increase Task Priority')
        AUTO_ASSIGN = 'AUTO_ASSIGN', _('Auto-Assign Responsible Users')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('rule name'), max_length=150)
    description = models.TextField(_('rule description'), blank=True)
    trigger_event = models.CharField(_('trigger event'), max_length=40, choices=TriggerEvent.choices)
    conditions = models.JSONField(
        _('rule conditions'),
        default=dict,
        blank=True,
        help_text=_('JSON conditions, e.g. {"priority": "HIGH", "department_code": "IT"}')
    )
    action_type = models.CharField(_('action type'), max_length=40, choices=ActionType.choices)
    action_config = models.JSONField(
        _('action configuration'),
        default=dict,
        blank=True,
        help_text=_('Action payload, e.g. {"message": "High priority task notification", "target_priority": "CRITICAL"}')
    )
    priority_order = models.PositiveIntegerField(_('execution priority order'), default=10)
    is_active = models.BooleanField(_('is active'), default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_automation_rules'
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('automation rule')
        verbose_name_plural = _('automation rules')
        ordering = ['priority_order', 'name']

    def __str__(self):
        return f"{self.name} [{self.get_trigger_event_display()} -> {self.get_action_type_display()}]"


class AutomationExecution(models.Model):
    """
    Immutable audit history of all automated actions executed by the engine.
    """
    class Status(models.TextChoices):
        SUCCESS = 'SUCCESS', _('Success')
        FAILED = 'FAILED', _('Failed')
        SKIPPED = 'SKIPPED', _('Skipped / No-Op')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(
        AutomationRule,
        verbose_name=_('triggered rule'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='executions'
    )
    trigger_event = models.CharField(_('trigger event'), max_length=40)
    target_repr = models.CharField(_('target entity'), max_length=255)
    target_id = models.CharField(_('target ID'), max_length=64, blank=True)
    status = models.CharField(_('execution status'), max_length=20, choices=Status.choices, default=Status.SUCCESS)
    result_summary = models.TextField(_('result summary'))
    error_message = models.TextField(_('error message'), blank=True)
    executed_at = models.DateTimeField(_('executed at'), auto_now_add=True)

    class Meta:
        verbose_name = _('automation execution log')
        verbose_name_plural = _('automation execution logs')
        ordering = ['-executed_at']
        indexes = [
            models.Index(fields=['-executed_at']),
            models.Index(fields=['status']),
            models.Index(fields=['trigger_event']),
        ]

    def __str__(self):
        return f"[{self.status}] {self.trigger_event} on {self.target_repr} ({self.executed_at.strftime('%Y-%m-%d %H:%M')})"
