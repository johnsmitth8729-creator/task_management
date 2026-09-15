import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from organization.models import Department


class AIConversation(models.Model):
    """
    Session history for AI Assistant chat sessions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('user'),
        on_delete=models.CASCADE,
        related_name='ai_conversations'
    )
    title = models.CharField(_('conversation topic'), max_length=200, default='New Discussion')
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('AI conversation')
        verbose_name_plural = _('AI conversations')
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.title} ({self.user.username})"


class AIMessage(models.Model):
    """
    Individual message in an AI conversation with role-aware context snapshots.
    """
    class Role(models.TextChoices):
        USER = 'USER', _('User')
        ASSISTANT = 'ASSISTANT', _('AI Assistant')
        SYSTEM = 'SYSTEM', _('System Prompt')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        AIConversation,
        verbose_name=_('conversation'),
        on_delete=models.CASCADE,
        related_name='messages'
    )
    role = models.CharField(_('message role'), max_length=20, choices=Role.choices)
    content = models.TextField(_('content text / markdown'))
    intent_detected = models.CharField(_('detected intent'), max_length=80, blank=True)
    context_snapshot = models.JSONField(
        _('role-scoped context snapshot'),
        default=dict,
        blank=True,
        help_text=_('Redacted, authorization-scoped database snapshot used to ground this response.')
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('AI message')
        verbose_name_plural = _('AI messages')
        ordering = ['created_at']

    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:50]}..."


class ManagementRiskIndicator(models.Model):
    """
    Proactively detected organizational risk or bottleneck identified by the AI engine.
    """
    class RiskType(models.TextChoices):
        DEADLINE_SPIKE = 'DEADLINE_SPIKE', _('Impending Overdue Deadline Spike')
        APPROVAL_BOTTLENECK = 'APPROVAL_BOTTLENECK', _('Stage 1 / Stage 2 Approval Bottleneck')
        WORKLOAD_IMBALANCE = 'WORKLOAD_IMBALANCE', _('Staff Workload Overload / Imbalance')
        SLA_VIOLATION_TREND = 'SLA_VIOLATION_TREND', _('Elevated SLA Violation Trend')
        LOW_COMPLETION_RATE = 'LOW_COMPLETION_RATE', _('Low Department Task Velocity')

    class Severity(models.TextChoices):
        LOW = 'LOW', _('Low')
        MEDIUM = 'MEDIUM', _('Medium')
        HIGH = 'HIGH', _('High')
        CRITICAL = 'CRITICAL', _('Critical')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    risk_type = models.CharField(_('risk category'), max_length=40, choices=RiskType.choices)
    severity = models.CharField(_('severity level'), max_length=20, choices=Severity.choices, default=Severity.MEDIUM)
    title = models.CharField(_('risk summary title'), max_length=255)
    description = models.TextField(_('detailed diagnosis and suggested remedy'))
    department = models.ForeignKey(
        Department,
        verbose_name=_('affected department'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='risk_indicators'
    )
    target_object_repr = models.CharField(_('target entity representation'), max_length=200, blank=True)
    metrics_payload = models.JSONField(_('diagnostic metrics payload'), default=dict, blank=True)
    is_resolved = models.BooleanField(_('is resolved'), default=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('resolved by user'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_risks'
    )
    detected_at = models.DateTimeField(_('detected at'), auto_now_add=True)
    resolved_at = models.DateTimeField(_('resolved at'), null=True, blank=True)

    class Meta:
        verbose_name = _('management risk indicator')
        verbose_name_plural = _('management risk indicators')
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['is_resolved', 'severity']),
            models.Index(fields=['department', 'is_resolved']),
        ]

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title} ({self.get_risk_type_display()})"


class ExecutiveBriefing(models.Model):
    """
    Synthesized executive intelligence reports generated for university leaders.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generated_for = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('generated for leader'),
        on_delete=models.CASCADE,
        related_name='executive_briefings'
    )
    title = models.CharField(_('briefing title'), max_length=255)
    period_start = models.DateField(_('period start date'))
    period_end = models.DateField(_('period end date'))
    summary_markdown = models.TextField(_('executive briefing text (markdown)'))
    kpis_snapshot = models.JSONField(_('KPI metrics snapshot payload'), default=dict, blank=True)
    created_at = models.DateTimeField(_('generated at'), auto_now_add=True)

    class Meta:
        verbose_name = _('executive briefing')
        verbose_name_plural = _('executive briefings')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.created_at:%Y-%m-%d})"
