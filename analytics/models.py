import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class AnalyticsThresholdConfig(models.Model):
    """
    Configurable performance and bottleneck thresholds for executive monitoring.
    Singleton-style configuration for university-wide alerts.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('configuration name'), max_length=150, default='Default Executive Thresholds')
    
    # Task alerts
    max_acceptable_overdue_tasks = models.PositiveIntegerField(
        _('maximum acceptable overdue tasks'),
        default=5,
        help_text=_('Trigger warning when total overdue tasks exceed this threshold.')
    )
    min_completion_rate_percent = models.DecimalField(
        _('minimum completion rate (%)'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('70.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text=_('Warning triggered if completion rate falls below this percentage.')
    )
    min_ontime_rate_percent = models.DecimalField(
        _('minimum on-time rate (%)'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('80.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text=_('Warning triggered if on-time completion falls below this percentage.')
    )
    max_rejection_rate_percent = models.DecimalField(
        _('maximum rejection rate (%)'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text=_('Warning triggered if task rejection rate exceeds this percentage.')
    )
    
    # KPI alerts
    min_kpi_score_percent = models.DecimalField(
        _('minimum acceptable KPI score (%)'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('70.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text=_('Warning triggered if average KPI score falls below this threshold.')
    )
    
    # Bottleneck alerts (in days)
    max_first_approval_wait_days = models.DecimalField(
        _('max first approval wait time (days)'),
        max_digits=4,
        decimal_places=1,
        default=Decimal('3.0'),
        help_text=_('Alert when average first approval queue time exceeds days.')
    )
    max_final_approval_wait_days = models.DecimalField(
        _('max final approval wait time (days)'),
        max_digits=4,
        decimal_places=1,
        default=Decimal('2.0'),
        help_text=_('Alert when average final approval queue time exceeds days.')
    )
    max_signature_wait_days = models.DecimalField(
        _('max signature wait time (days)'),
        max_digits=4,
        decimal_places=1,
        default=Decimal('2.0'),
        help_text=_('Alert when average electronic signature queue time exceeds days.')
    )

    is_active = models.BooleanField(_('is active'), default=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('Analytics Threshold Configuration')
        verbose_name_plural = _('Analytics Threshold Configurations')
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"

    @classmethod
    def get_active(cls):
        """Returns the active threshold config or default instance."""
        active = cls.objects.filter(is_active=True).first()
        if not active:
            active = cls.objects.create(name='Default University Thresholds')
        return active


class SavedReportConfiguration(models.Model):
    """
    Stores user-defined or system preset report configurations in the Report Center.
    """
    class ReportTypes(models.TextChoices):
        UNIVERSITY_TASKS = 'UNIVERSITY_TASKS', _('University Task Overview Report')
        DEPARTMENT_PERFORMANCE = 'DEPARTMENT_PERFORMANCE', _('Department Performance Report')
        KPI_SUMMARY = 'KPI_SUMMARY', _('KPI & Evaluation Report')
        PAYROLL_ANALYTICS = 'PAYROLL_ANALYTICS', _('Payroll & Compensation Analytics Report')
        SIGNATURE_AUDIT = 'SIGNATURE_AUDIT', _('Electronic Signature & Verification Audit Report')
        DEADLINE_COMPLIANCE = 'DEADLINE_COMPLIANCE', _('Deadline Compliance & Bottleneck Report')
        HR_DISTRIBUTION = 'HR_DISTRIBUTION', _('HR Workforce & Headcount Distribution Report')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('report name'), max_length=200)
    report_type = models.CharField(_('report type'), max_length=50, choices=ReportTypes.choices)
    description = models.TextField(_('description'), blank=True)
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='saved_reports'
    )
    is_system_preset = models.BooleanField(_('is system preset'), default=False)
    parameters = models.JSONField(_('filter parameters'), default=dict, blank=True)
    
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('Saved Report Configuration')
        verbose_name_plural = _('Saved Report Configurations')
        ordering = ['-is_system_preset', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_report_type_display()})"
