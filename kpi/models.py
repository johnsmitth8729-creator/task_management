import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


class KPICategory(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=150)
    code = models.CharField(_('code'), max_length=50, unique=True)
    description = models.TextField(_('description'), blank=True)
    order = models.IntegerField(_('display order'), default=1)
    is_active = models.BooleanField(_('active'), default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='created_kpi_categories',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = _('KPI category')
        verbose_name_plural = _('KPI categories')

    def __str__(self):
        return self.name


class KPIPeriod(TimeStampedModel):
    class PeriodType(models.TextChoices):
        MONTHLY = 'MONTHLY', _('Monthly')
        QUARTERLY = 'QUARTERLY', _('Quarterly')
        YEARLY = 'YEARLY', _('Yearly')

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        OPEN = 'OPEN', _('Open / Active')
        CALCULATING = 'CALCULATING', _('Calculating')
        UNDER_REVIEW = 'UNDER_REVIEW', _('Under Review')
        HR_VERIFIED = 'HR_VERIFIED', _('HR Verified')
        PENDING_RECTOR_APPROVAL = 'PENDING_RECTOR_APPROVAL', _('Pending Rector Approval')
        RECTOR_APPROVED = 'RECTOR_APPROVED', _('Rector Approved')
        RECTOR_SIGNED = 'RECTOR_SIGNED', _('Rector Signed / Finalized')
        CLOSED = 'CLOSED', _('Closed / Archived')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=150)
    code = models.CharField(_('code'), max_length=50, unique=True)
    period_type = models.CharField(_('period type'), max_length=20, choices=PeriodType.choices, default=PeriodType.QUARTERLY)
    start_date = models.DateField(_('start date'))
    end_date = models.DateField(_('end date'))
    status = models.CharField(_('status'), max_length=30, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='created_kpi_periods',
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('approved by'),
        on_delete=models.SET_NULL,
        related_name='approved_kpi_periods',
        null=True,
        blank=True,
    )
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('signed by'),
        on_delete=models.SET_NULL,
        related_name='signed_kpi_periods',
        null=True,
        blank=True,
    )
    signed_at = models.DateTimeField(_('signed at'), null=True, blank=True)
    rejection_reason = models.TextField(_('rejection reason'), blank=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['status']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = _('KPI period')
        verbose_name_plural = _('KPI periods')

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    @property
    def is_immutable(self) -> bool:
        return self.status in [self.Status.RECTOR_SIGNED, self.Status.CLOSED]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({'end_date': _('End date cannot be earlier than start date.')})


class KPIDefinition(TimeStampedModel):
    class MeasurementType(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', _('Percentage (0-100%)')
        NUMERIC = 'NUMERIC', _('Numeric Value')
        BOOLEAN = 'BOOLEAN', _('Yes / No')
        COUNT = 'COUNT', _('Count / Quantity')
        RATING = 'RATING', _('Rating Score (1-5)')
        TASK_COMPLETION = 'TASK_COMPLETION', _('Task Completion Rate')
        DEADLINE_COMPLIANCE = 'DEADLINE_COMPLIANCE', _('Deadline Compliance Rate')
        QUALITY = 'QUALITY', _('Work & Deliverable Quality')
        DURATION = 'DURATION', _('Turnaround Duration')
        CUSTOM = 'CUSTOM', _('Custom Indicator')

    class SourceType(models.TextChoices):
        TASK_SYSTEM = 'TASK_SYSTEM', _('Task Management Subsystem (Automatic)')
        WORKFLOW_SYSTEM = 'WORKFLOW_SYSTEM', _('Workflow Subsystem (Automatic)')
        MANUAL_MANAGER_EVALUATION = 'MANUAL_MANAGER_EVALUATION', _('Manual Manager Evaluation')
        HR_EVALUATION = 'HR_EVALUATION', _('HR Department Evaluation')
        STRATEGIC_TARGET = 'STRATEGIC_TARGET', _('Strategic Target / Executive Metric')
        OTHER = 'OTHER', _('Other Source')

    class Direction(models.TextChoices):
        HIGHER_IS_BETTER = 'HIGHER_IS_BETTER', _('Higher is Better')
        LOWER_IS_BETTER = 'LOWER_IS_BETTER', _('Lower is Better')
        TARGET_IS_BEST = 'TARGET_IS_BEST', _('Target is Best')

    class NoDataPolicy(models.TextChoices):
        EXCLUDED = 'EXCLUDED', _('Exclude from Score Calculation (No Penalty)')
        ZERO = 'ZERO', _('Treat as Zero Score (0%)')
        MANUAL_REVIEW = 'MANUAL_REVIEW', _('Flag for Manual Review')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=255)
    code = models.CharField(_('code'), max_length=50, unique=True)
    description = models.TextField(_('description'), blank=True)
    category = models.ForeignKey(
        KPICategory,
        verbose_name=_('category'),
        on_delete=models.PROTECT,
        related_name='definitions',
    )
    measurement_type = models.CharField(
        _('measurement type'),
        max_length=30,
        choices=MeasurementType.choices,
        default=MeasurementType.PERCENTAGE,
    )
    source_type = models.CharField(
        _('source type'),
        max_length=35,
        choices=SourceType.choices,
        default=SourceType.MANUAL_MANAGER_EVALUATION,
    )
    direction = models.CharField(
        _('direction'),
        max_length=25,
        choices=Direction.choices,
        default=Direction.HIGHER_IS_BETTER,
    )
    no_data_policy = models.CharField(
        _('no data policy'),
        max_length=20,
        choices=NoDataPolicy.choices,
        default=NoDataPolicy.EXCLUDED,
    )
    target_value = models.DecimalField(_('default target'), max_digits=8, decimal_places=2, default=Decimal('100.00'))
    weight = models.DecimalField(_('default weight (%)'), max_digits=5, decimal_places=2, default=Decimal('10.00'))
    configured_weight = models.DecimalField(_('configured weight (%)'), max_digits=5, decimal_places=2, default=Decimal('10.00'))
    min_value = models.DecimalField(_('min value'), max_digits=8, decimal_places=2, default=Decimal('0.00'))
    max_value = models.DecimalField(_('max value'), max_digits=8, decimal_places=2, default=Decimal('100.00'))

    # Optional organizational applicability filters
    applicable_department = models.ForeignKey(
        'organization.Department',
        verbose_name=_('applicable department'),
        on_delete=models.SET_NULL,
        related_name='applicable_kpis',
        null=True,
        blank=True,
    )
    applicable_position = models.ForeignKey(
        'organization.Position',
        verbose_name=_('applicable position'),
        on_delete=models.SET_NULL,
        related_name='applicable_kpis',
        null=True,
        blank=True,
    )
    applicable_grade = models.ForeignKey(
        'hr.EmployeeGrade',
        verbose_name=_('applicable grade'),
        on_delete=models.SET_NULL,
        related_name='applicable_kpis',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='created_kpi_definitions',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
            models.Index(fields=['source_type']),
        ]
        verbose_name = _('KPI definition')
        verbose_name_plural = _('KPI definitions')

    def __str__(self):
        return f"{self.name} [{self.category.name}]"

    def save(self, *args, **kwargs):
        if not self.configured_weight:
            self.configured_weight = self.weight
        self.weight = self.configured_weight
        super().save(*args, **kwargs)


class KPIAssignment(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kpi = models.ForeignKey(
        KPIDefinition,
        verbose_name=_('KPI definition'),
        on_delete=models.PROTECT,
        related_name='assignments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('employee'),
        on_delete=models.CASCADE,
        related_name='kpi_assignments',
    )
    period = models.ForeignKey(
        KPIPeriod,
        verbose_name=_('period'),
        on_delete=models.CASCADE,
        related_name='assignments',
    )
    target_value = models.DecimalField(_('target value'), max_digits=8, decimal_places=2)
    weight = models.DecimalField(_('weight (%)'), max_digits=5, decimal_places=2, default=Decimal('10.00'))
    configured_weight = models.DecimalField(_('configured weight (%)'), max_digits=5, decimal_places=2, default=Decimal('10.00'))
    normalized_weight = models.DecimalField(_('normalized weight (%)'), max_digits=5, decimal_places=2, default=Decimal('10.00'))
    source_type = models.CharField(_('source type'), max_length=35, blank=True)
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('designated evaluator'),
        on_delete=models.SET_NULL,
        related_name='assigned_kpi_evaluations',
        null=True,
        blank=True,
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('assigned by'),
        on_delete=models.SET_NULL,
        related_name='assigned_kpi_definitions',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['user', 'kpi']
        indexes = [
            models.Index(fields=['user', 'period']),
            models.Index(fields=['period', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['kpi', 'user', 'period'],
                name='unique_user_kpi_per_period',
            )
        ]
        verbose_name = _('KPI assignment')
        verbose_name_plural = _('KPI assignments')

    def __str__(self):
        return f"{self.user.display_name} — {self.kpi.name} ({self.period.code})"

    def save(self, *args, **kwargs):
        if not self.configured_weight:
            self.configured_weight = self.weight
        if not self.normalized_weight:
            self.normalized_weight = self.configured_weight
        self.weight = self.normalized_weight
        if not self.source_type and self.kpi:
            self.source_type = self.kpi.source_type
        super().save(*args, **kwargs)


class KPIResult(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        SUBMITTED = 'SUBMITTED', _('Submitted for Review')
        REVIEWED = 'REVIEWED', _('Reviewed by Manager')
        HR_VERIFIED = 'HR_VERIFIED', _('HR Verified')
        APPROVED = 'APPROVED', _('Approved & Finalized')
        LOCKED = 'LOCKED', _('Signed & Locked')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.OneToOneField(
        KPIAssignment,
        verbose_name=_('KPI assignment'),
        on_delete=models.CASCADE,
        related_name='result',
    )
    version = models.PositiveIntegerField(_('result version'), default=1)
    actual_value = models.DecimalField(_('actual value'), max_digits=8, decimal_places=2, default=Decimal('0.00'))
    raw_score = models.DecimalField(_('raw score (0-100)'), max_digits=5, decimal_places=2, default=Decimal('0.00'))
    configured_weight = models.DecimalField(_('configured weight (%)'), max_digits=5, decimal_places=2, default=Decimal('0.00'))
    normalized_weight = models.DecimalField(_('normalized weight (%)'), max_digits=5, decimal_places=2, default=Decimal('0.00'))
    weighted_score = models.DecimalField(_('weighted score'), max_digits=5, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(_('status'), max_length=25, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(_('evaluator notes / feedback'), blank=True)
    calculation_evidence = models.JSONField(_('calculation evidence & task breakdown'), default=dict, blank=True)
    is_locked = models.BooleanField(_('locked against modification'), default=False)
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('evaluated by'),
        on_delete=models.SET_NULL,
        related_name='evaluated_kpi_results',
        null=True,
        blank=True,
    )
    evaluated_at = models.DateTimeField(_('evaluated at'), null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['is_locked']),
        ]
        verbose_name = _('KPI result')
        verbose_name_plural = _('KPI results')

    def __str__(self):
        return f"{self.assignment.user.display_name} — {self.assignment.kpi.name}: {self.actual_value} ({self.weighted_score} pts)"


class KPISnapshot(TimeStampedModel):
    """
    Immutable cryptographic snapshot of the entire university KPI package for a period
    at the exact moment of Rector digital signing.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period = models.ForeignKey(
        KPIPeriod,
        verbose_name=_('KPI period'),
        on_delete=models.PROTECT,
        related_name='snapshots',
    )
    signature = models.ForeignKey(
        'signatures.ElectronicSignature',
        verbose_name=_('electronic signature'),
        on_delete=models.SET_NULL,
        related_name='kpi_snapshots',
        null=True,
        blank=True,
    )
    canonical_payload = models.JSONField(
        _('canonical payload'),
        help_text=_('Deterministic JSON snapshot containing all employee scores and evidence.'),
    )
    payload_hash = models.CharField(
        _('payload hash'),
        max_length=64,
        help_text=_('SHA-256 hash of the canonical payload.'),
    )
    total_employees = models.PositiveIntegerField(_('total evaluated employees'), default=0)
    average_score = models.DecimalField(_('university average score'), max_digits=5, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('KPI period snapshot')
        verbose_name_plural = _('KPI period snapshots')

    def __str__(self):
        return f"Snapshot {self.period.code} ({self.average_score}% avg — {self.total_employees} staff)"

    def verify_integrity(self) -> bool:
        from signatures.crypto import canonical_json, compute_sha256
        computed_hash = compute_sha256(canonical_json(self.canonical_payload))
        return computed_hash == self.payload_hash


class KPICorrectionRequest(TimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', _('Correction Requested')
        HR_REVIEW = 'HR_REVIEW', _('Under HR Review')
        PENDING_RECTOR = 'PENDING_RECTOR', _('Pending Rector Decision')
        APPROVED = 'APPROVED', _('Correction Approved')
        REJECTED = 'REJECTED', _('Correction Rejected')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    result = models.ForeignKey(
        KPIResult,
        verbose_name=_('original KPI result'),
        on_delete=models.PROTECT,
        related_name='correction_requests',
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('requester'),
        on_delete=models.PROTECT,
        related_name='kpi_corrections_requested',
    )
    requested_actual_value = models.DecimalField(_('requested actual value'), max_digits=8, decimal_places=2)
    reason = models.TextField(_('justification / correction reason'))
    evidence = models.TextField(_('supporting evidence / documentation'), blank=True)
    status = models.CharField(_('status'), max_length=25, choices=Status.choices, default=Status.REQUESTED)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('reviewed by'),
        on_delete=models.SET_NULL,
        related_name='kpi_corrections_reviewed',
        null=True,
        blank=True,
    )
    review_notes = models.TextField(_('HR review notes'), blank=True)
    rector_decision_reason = models.TextField(_('rector decision reason'), blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('KPI correction request')
        verbose_name_plural = _('KPI correction requests')

    def __str__(self):
        return f"Correction for {self.result.assignment} [{self.get_status_display()}]"
