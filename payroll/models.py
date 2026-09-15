import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from payroll.validators import (
    validate_non_negative_decimal,
    validate_percentage,
    validate_positive_decimal,
)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# 1. SalaryProfile & SalaryHistory
# ---------------------------------------------------------------------------

class SalaryProfile(TimeStampedModel):
    class SalaryType(models.TextChoices):
        MONTHLY = 'MONTHLY', _('Monthly Base Salary')
        DAILY = 'DAILY', _('Daily Rate')
        HOURLY = 'HOURLY', _('Hourly Rate')

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', _('Active')
        INACTIVE = 'INACTIVE', _('Inactive / Historical')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('employee'),
        on_delete=models.CASCADE,
        related_name='salary_profiles',
    )
    base_salary = models.DecimalField(
        _('base salary amount'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_positive_decimal],
    )
    currency = models.CharField(_('currency'), max_length=10, default='UZS')
    effective_from = models.DateField(_('effective from date'))
    effective_to = models.DateField(_('effective to date'), null=True, blank=True)
    salary_type = models.CharField(
        _('salary calculation type'),
        max_length=20,
        choices=SalaryType.choices,
        default=SalaryType.MONTHLY,
    )
    status = models.CharField(
        _('profile status'),
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    notes = models.TextField(_('notes / reason'), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='created_salary_profiles',
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('updated by'),
        on_delete=models.SET_NULL,
        related_name='updated_salary_profiles',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-effective_from', '-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['effective_from']),
        ]
        verbose_name = _('salary profile')
        verbose_name_plural = _('salary profiles')

    def __str__(self):
        return f"{self.user.display_name} — {self.base_salary:,.2f} {self.currency} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def clean(self):
        super().clean()
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValidationError({'effective_to': _('Effective to date cannot be before effective from date.')})


class SalaryHistory(models.Model):
    """Immutable audit trail of all base salary adjustments."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('employee'),
        on_delete=models.CASCADE,
        related_name='salary_histories',
    )
    previous_salary = models.DecimalField(
        _('previous salary'),
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    new_salary = models.DecimalField(
        _('new salary'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_positive_decimal],
    )
    currency = models.CharField(_('currency'), max_length=10, default='UZS')
    effective_from = models.DateField(_('effective from date'))
    reason = models.TextField(_('reason for adjustment'))
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('changed by'),
        on_delete=models.SET_NULL,
        related_name='authorized_salary_changes',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_('timestamp'), auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
        verbose_name = _('salary history record')
        verbose_name_plural = _('salary history records')

    def __str__(self):
        prev = f"{self.previous_salary:,.2f}" if self.previous_salary else "None"
        return f"{self.user.display_name}: {prev} → {self.new_salary:,.2f} {self.currency} on {self.effective_from}"


class SalaryBand(TimeStampedModel):
    """Institutional guideline salary ranges by employee grade."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grade = models.ForeignKey(
        'hr.EmployeeGrade',
        verbose_name=_('employee grade'),
        on_delete=models.CASCADE,
        related_name='salary_bands',
    )
    min_salary = models.DecimalField(
        _('minimum salary'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_positive_decimal],
    )
    max_salary = models.DecimalField(
        _('maximum salary'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_positive_decimal],
    )
    currency = models.CharField(_('currency'), max_length=10, default='UZS')
    effective_from = models.DateField(_('effective from'))
    effective_to = models.DateField(_('effective to'), null=True, blank=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['grade__rank', 'min_salary']
        verbose_name = _('salary band')
        verbose_name_plural = _('salary bands')

    def __str__(self):
        return f"{self.grade.code} Band: {self.min_salary:,.2f} - {self.max_salary:,.2f} {self.currency}"

    def clean(self):
        super().clean()
        if self.min_salary and self.max_salary and self.min_salary > self.max_salary:
            raise ValidationError({'max_salary': _('Maximum salary cannot be less than minimum salary.')})


# ---------------------------------------------------------------------------
# 2. PayrollPeriod
# ---------------------------------------------------------------------------

class PayrollPeriod(TimeStampedModel):
    class PeriodType(models.TextChoices):
        MONTHLY = 'MONTHLY', _('Monthly')
        QUARTERLY = 'QUARTERLY', _('Quarterly')
        YEARLY = 'YEARLY', _('Yearly')

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        OPEN = 'OPEN', _('Open / In Progress')
        CALCULATING = 'CALCULATING', _('Calculating')
        PENDING_APPROVAL = 'PENDING_APPROVAL', _('Pending Final Approval')
        APPROVED = 'APPROVED', _('Approved & Locked')
        CLOSED = 'CLOSED', _('Closed')
        CANCELLED = 'CANCELLED', _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('period name'), max_length=150)
    code = models.CharField(_('period code'), max_length=50, unique=True)
    period_type = models.CharField(
        _('period type'),
        max_length=20,
        choices=PeriodType.choices,
        default=PeriodType.MONTHLY,
    )
    start_date = models.DateField(_('start date'))
    end_date = models.DateField(_('end date'))
    status = models.CharField(
        _('status'),
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='created_payroll_periods',
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('approved by'),
        on_delete=models.SET_NULL,
        related_name='approved_payroll_periods',
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(_('approved at'), null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('closed by'),
        on_delete=models.SET_NULL,
        related_name='closed_payroll_periods',
        null=True,
        blank=True,
    )
    closed_at = models.DateTimeField(_('closed at'), null=True, blank=True)

    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['status']),
            models.Index(fields=['start_date', 'end_date']),
        ]
        verbose_name = _('payroll period')
        verbose_name_plural = _('payroll periods')

    def __str__(self):
        return f"{self.name} [{self.code}] ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({'end_date': _('End date cannot be earlier than start date.')})


# ---------------------------------------------------------------------------
# 3. CompensationComponent, Tax & KPI Rules
# ---------------------------------------------------------------------------

class CompensationComponent(TimeStampedModel):
    class ComponentType(models.TextChoices):
        ALLOWANCE = 'ALLOWANCE', _('Allowance')
        BONUS = 'BONUS', _('Bonus')
        DEDUCTION = 'DEDUCTION', _('Deduction')

    class CalculationType(models.TextChoices):
        FIXED = 'FIXED', _('Fixed Monetary Amount')
        PERCENTAGE = 'PERCENTAGE', _('Percentage of Base Salary')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('component name'), max_length=150)
    code = models.CharField(_('component code'), max_length=50, unique=True)
    component_type = models.CharField(
        _('component type'),
        max_length=20,
        choices=ComponentType.choices,
        default=ComponentType.ALLOWANCE,
    )
    calculation_type = models.CharField(
        _('calculation type'),
        max_length=20,
        choices=CalculationType.choices,
        default=CalculationType.FIXED,
    )
    default_value = models.DecimalField(
        _('default rate / value'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_non_negative_decimal],
        default=Decimal('0.00'),
    )
    is_taxable = models.BooleanField(_('is subject to tax'), default=True)
    is_active = models.BooleanField(_('is active'), default=True)
    description = models.TextField(_('description / purpose'), blank=True)

    class Meta:
        ordering = ['component_type', 'name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['component_type', 'is_active']),
        ]
        verbose_name = _('compensation component')
        verbose_name_plural = _('compensation components')

    def __str__(self):
        return f"{self.name} ({self.get_component_type_display()} — {self.code})"


class PayrollTaxRule(TimeStampedModel):
    class AppliesTo(models.TextChoices):
        GROSS = 'GROSS', _('Gross Salary')
        TAXABLE_GROSS = 'TAXABLE_GROSS', _('Taxable Gross (Taxable Allowances + Base)')
        BASE_SALARY = 'BASE_SALARY', _('Base Salary Only')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('tax rule name'), max_length=150)
    code = models.CharField(_('tax code'), max_length=50, unique=True)
    percentage = models.DecimalField(
        _('tax rate (%)'),
        max_digits=5,
        decimal_places=2,
        validators=[validate_percentage],
        default=Decimal('0.00'),
    )
    fixed_amount = models.DecimalField(
        _('fixed tax deduction amount'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_non_negative_decimal],
        default=Decimal('0.00'),
    )
    applies_to = models.CharField(
        _('applies to base'),
        max_length=25,
        choices=AppliesTo.choices,
        default=AppliesTo.TAXABLE_GROSS,
    )
    effective_from = models.DateField(_('effective from date'), default=timezone.now)
    effective_to = models.DateField(_('effective to date'), null=True, blank=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['-effective_from', 'name']
        verbose_name = _('payroll tax rule')
        verbose_name_plural = _('payroll tax rules')

    def __str__(self):
        return f"{self.name} ({self.percentage}% of {self.get_applies_to_display()})"


class KPIPayrollRule(TimeStampedModel):
    class BonusType(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', _('Percentage of Base Salary')
        FIXED = 'FIXED', _('Fixed Monetary Amount')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('rule name'), max_length=150)
    min_score = models.DecimalField(
        _('minimum score threshold (inclusive)'),
        max_digits=5,
        decimal_places=2,
        validators=[validate_percentage],
    )
    max_score = models.DecimalField(
        _('maximum score threshold (inclusive)'),
        max_digits=5,
        decimal_places=2,
        validators=[validate_percentage],
    )
    bonus_type = models.CharField(
        _('bonus type'),
        max_length=20,
        choices=BonusType.choices,
        default=BonusType.PERCENTAGE,
    )
    bonus_value = models.DecimalField(
        _('bonus value (% or fixed amount)'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_non_negative_decimal],
    )
    effective_from = models.DateField(_('effective from'), default=timezone.now)
    effective_to = models.DateField(_('effective to'), null=True, blank=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['min_score']
        verbose_name = _('KPI payroll bonus rule')
        verbose_name_plural = _('KPI payroll bonus rules')

    def __str__(self):
        val = f"{self.bonus_value}%" if self.bonus_type == self.BonusType.PERCENTAGE else f"{self.bonus_value:,.2f} UZS"
        return f"{self.name} (Score {self.min_score}-{self.max_score} → {val})"

    def clean(self):
        super().clean()
        if self.min_score and self.max_score and self.min_score > self.max_score:
            raise ValidationError({'max_score': _('Maximum score cannot be less than minimum score.')})


# ---------------------------------------------------------------------------
# 4. PayrollRecord & Line Items
# ---------------------------------------------------------------------------

class PayrollRecord(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        CALCULATED = 'CALCULATED', _('Calculated')
        PENDING_APPROVAL = 'PENDING_APPROVAL', _('Pending Approval')
        APPROVED = 'APPROVED', _('Approved & Locked')
        PAID = 'PAID', _('Paid')
        CANCELLED = 'CANCELLED', _('Cancelled')

    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', _('Unpaid')
        READY = 'READY', _('Ready for Disbursement')
        PAID = 'PAID', _('Paid')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period = models.ForeignKey(
        PayrollPeriod,
        verbose_name=_('payroll period'),
        on_delete=models.PROTECT,
        related_name='records',
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('employee'),
        on_delete=models.PROTECT,
        related_name='payroll_records',
    )

    # Immutable Historical Snapshots
    employee_name_snapshot = models.CharField(_('employee full name at calculation'), max_length=255)
    employee_username_snapshot = models.CharField(_('employee username at calculation'), max_length=150)
    department_snapshot = models.CharField(_('department at calculation'), max_length=255, blank=True)
    position_snapshot = models.CharField(_('position at calculation'), max_length=255, blank=True)
    grade_snapshot = models.CharField(_('grade at calculation'), max_length=100, blank=True)
    kpi_score_snapshot = models.DecimalField(
        _('approved KPI score at calculation'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
    )

    # Monetary Breakdown
    base_salary = models.DecimalField(
        _('base salary'),
        max_digits=18,
        decimal_places=2,
        validators=[validate_non_negative_decimal],
    )
    total_allowances = models.DecimalField(
        _('total allowances'),
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    total_bonuses = models.DecimalField(
        _('total standard bonuses'),
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    kpi_bonus = models.DecimalField(
        _('performance / KPI bonus'),
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    total_deductions = models.DecimalField(
        _('total non-tax deductions'),
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    gross_salary = models.DecimalField(
        _('gross salary'),
        max_digits=18,
        decimal_places=2,
    )
    tax_total = models.DecimalField(
        _('total tax deducted'),
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    net_salary = models.DecimalField(
        _('net salary payable'),
        max_digits=18,
        decimal_places=2,
    )
    currency = models.CharField(_('currency'), max_length=10, default='UZS')

    # Lifecycle & Approvals
    status = models.CharField(
        _('status'),
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    calculated_at = models.DateTimeField(_('calculated at'), null=True, blank=True)
    approved_at = models.DateTimeField(_('approved at'), null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('approved by'),
        on_delete=models.SET_NULL,
        related_name='approved_payroll_records',
        null=True,
        blank=True,
    )
    notes = models.TextField(_('calculation notes / remarks'), blank=True)

    # Payment Status & Details
    payment_status = models.CharField(
        _('payment status'),
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    paid_at = models.DateTimeField(_('disbursed at'), null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('paid by / disbursed by'),
        on_delete=models.SET_NULL,
        related_name='disbursed_payroll_records',
        null=True,
        blank=True,
    )
    payment_reference = models.CharField(_('payment document / transaction reference'), max_length=100, blank=True)

    class Meta:
        ordering = ['-period__start_date', 'employee_name_snapshot']
        indexes = [
            models.Index(fields=['period', 'employee']),
            models.Index(fields=['status']),
            models.Index(fields=['payment_status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['period', 'employee'],
                name='unique_employee_payroll_per_period',
            )
        ]
        verbose_name = _('payroll record')
        verbose_name_plural = _('payroll records')

    def __str__(self):
        return f"{self.employee_name_snapshot} ({self.period.code}): Net {self.net_salary:,.2f} {self.currency} [{self.get_status_display()}]"

    @property
    def taxable_gross(self) -> Decimal:
        """Sum of all taxable earnings (base salary, taxable allowances, bonuses, KPI)."""
        taxable_lines = [
            line.amount
            for line in self.lines.all()
            if line.taxable and line.component_type in [
                CompensationComponent.ComponentType.ALLOWANCE,
                CompensationComponent.ComponentType.BONUS,
            ]
        ]
        if taxable_lines:
            return sum(taxable_lines, Decimal('0.00')).quantize(Decimal('0.01'))
        return self.base_salary.quantize(Decimal('0.01'))


class PayrollLine(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payroll = models.ForeignKey(
        PayrollRecord,
        verbose_name=_('payroll record'),
        on_delete=models.CASCADE,
        related_name='lines',
    )
    component = models.ForeignKey(
        CompensationComponent,
        verbose_name=_('component source'),
        on_delete=models.SET_NULL,
        related_name='payroll_lines',
        null=True,
        blank=True,
    )
    name_snapshot = models.CharField(_('item description snapshot'), max_length=150)
    component_type = models.CharField(
        _('component type'),
        max_length=20,
        choices=CompensationComponent.ComponentType.choices,
    )
    calculation_type = models.CharField(
        _('calculation type'),
        max_length=20,
        choices=CompensationComponent.CalculationType.choices,
    )
    rate_or_value = models.DecimalField(
        _('rate / base value'),
        max_digits=18,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    amount = models.DecimalField(
        _('calculated line amount'),
        max_digits=18,
        decimal_places=2,
    )
    taxable = models.BooleanField(_('is taxable'), default=True)
    description = models.TextField(_('line details / memo'), blank=True)

    class Meta:
        ordering = ['component_type', 'name_snapshot']
        verbose_name = _('payroll line item')
        verbose_name_plural = _('payroll line items')

    def __str__(self):
        return f"{self.name_snapshot}: {self.amount:,.2f} ({self.get_component_type_display()})"


class PayrollAdjustment(TimeStampedModel):
    class AdjustmentType(models.TextChoices):
        BONUS = 'BONUS', _('Discretionary Bonus')
        ALLOWANCE = 'ALLOWANCE', _('Special Allowance')
        DEDUCTION = 'DEDUCTION', _('Penalty / Deduction')
        CORRECTION = 'CORRECTION', _('Calculation Correction')

    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending Approval')
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payroll = models.ForeignKey(
        PayrollRecord,
        verbose_name=_('associated payroll record'),
        on_delete=models.CASCADE,
        related_name='adjustments',
        null=True,
        blank=True,
    )
    period = models.ForeignKey(
        PayrollPeriod,
        verbose_name=_('payroll period'),
        on_delete=models.CASCADE,
        related_name='adjustments',
        null=True,
        blank=True,
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('employee'),
        on_delete=models.CASCADE,
        related_name='payroll_adjustments',
    )
    type = models.CharField(
        _('adjustment type'),
        max_length=20,
        choices=AdjustmentType.choices,
    )
    amount = models.DecimalField(
        _('adjustment amount'),
        max_digits=18,
        decimal_places=2,
    )
    reason = models.TextField(_('mandatory reason'))
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='created_payroll_adjustments',
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('approved by'),
        on_delete=models.SET_NULL,
        related_name='approved_payroll_adjustments',
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(_('approved at'), null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('payroll adjustment')
        verbose_name_plural = _('payroll adjustments')

    def __str__(self):
        return f"{self.get_type_display()} for {self.employee.display_name}: {self.amount:,.2f} ({self.get_status_display()})"


class PayrollPermissionConfig(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('authorized user'),
        on_delete=models.CASCADE,
        related_name='payroll_authority',
    )
    can_view_payroll = models.BooleanField(_('can view payroll'), default=True)
    can_manage_salary = models.BooleanField(_('can manage employee salaries'), default=False)
    can_manage_compensation = models.BooleanField(_('can manage compensation components'), default=False)
    can_calculate_payroll = models.BooleanField(_('can calculate payroll'), default=False)
    can_create_adjustment = models.BooleanField(_('can create adjustments'), default=False)
    can_approve_payroll = models.BooleanField(_('can approve payroll'), default=False)
    can_mark_paid = models.BooleanField(_('can mark payroll as paid'), default=False)
    can_view_payroll_reports = models.BooleanField(_('can view payroll reports'), default=False)
    can_manage_tax_rules = models.BooleanField(_('can manage tax rules'), default=False)
    can_manage_kpi_payroll_rules = models.BooleanField(_('can manage KPI payroll rules'), default=False)

    class Meta:
        verbose_name = _('payroll authority configuration')
        verbose_name_plural = _('payroll authority configurations')

    def __str__(self):
        return f"Payroll Authority ({self.user.display_name})"
