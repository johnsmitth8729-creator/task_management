from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from core.models import AuditLog, Notification, log_audit
from hr.services import get_hr_permission
from kpi.models import KPIAssignment, KPIPeriod, KPIResult
from payroll.models import (
    CompensationComponent,
    KPIPayrollRule,
    PayrollAdjustment,
    PayrollLine,
    PayrollPeriod,
    PayrollRecord,
    PayrollTaxRule,
    SalaryHistory,
    SalaryProfile,
)


def quantize_money(amount: Decimal) -> Decimal:
    """Standardizes monetary rounding to 2 decimal places using standard financial ROUND_HALF_UP."""
    if amount is None:
        return Decimal('0.00')
    return Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 1. Salary Profile & History Management
# ---------------------------------------------------------------------------

@transaction.atomic
def create_salary_profile(
    actor: User,
    user: User,
    base_salary: Decimal,
    effective_from=None,
    currency: str = 'UZS',
    salary_type: str = SalaryProfile.SalaryType.MONTHLY,
    notes: str = '',
    request=None,
) -> SalaryProfile:
    """
    Creates a new active salary profile for an employee, archives previous active profiles,
    and writes an immutable SalaryHistory audit record.
    """
    if effective_from is None:
        effective_from = timezone.now().date()
    base_salary = quantize_money(base_salary)
    if base_salary <= Decimal('0.00'):
        raise ValidationError(_('Base salary must be strictly greater than zero.'))

    # Fetch previous active profile
    prev_profile = SalaryProfile.objects.filter(user=user, status=SalaryProfile.Status.ACTIVE).first()
    prev_salary = prev_profile.base_salary if prev_profile else None

    # Deactivate existing active profiles
    if prev_profile:
        prev_profile.status = SalaryProfile.Status.INACTIVE
        if not prev_profile.effective_to or prev_profile.effective_to > effective_from:
            prev_profile.effective_to = effective_from
        prev_profile.updated_by = actor
        prev_profile.save()

    # Create new active profile
    new_profile = SalaryProfile.objects.create(
        user=user,
        base_salary=base_salary,
        currency=currency,
        effective_from=effective_from,
        salary_type=salary_type,
        status=SalaryProfile.Status.ACTIVE,
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )

    # Record immutable SalaryHistory
    SalaryHistory.objects.create(
        user=user,
        previous_salary=prev_salary,
        new_salary=base_salary,
        currency=currency,
        effective_from=effective_from,
        reason=notes or _('Salary Profile Adjustment'),
        changed_by=actor,
    )

    # Audit Logging
    action = AuditLog.Actions.SALARY_CHANGED if prev_salary else AuditLog.Actions.SALARY_CREATED
    log_audit(
        actor=actor,
        action=action,
        target_repr=f"{user.display_name} Salary",
        details={
            'user_id': str(user.id),
            'previous_salary': float(prev_salary) if prev_salary else None,
            'new_salary': float(base_salary),
            'currency': currency,
            'effective_from': str(effective_from),
            'notes': notes,
        },
        request=request,
    )

    # In-App Notification
    if actor.id != user.id:
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.NotificationType.SALARY_CHANGED,
            title=_('Salary Updated'),
            message=_(
                'Your compensation profile has been updated to %(salary)s %(currency)s effective %(date)s.'
            ) % {
                'salary': f"{base_salary:,.2f}",
                'currency': currency,
                'date': str(effective_from),
            },
        )

    return new_profile


# ---------------------------------------------------------------------------
# 2. Calculation Engine
# ---------------------------------------------------------------------------

@transaction.atomic
def calculate_payroll(
    employee: User,
    period: PayrollPeriod,
    actor: User = None,
    request=None,
) -> PayrollRecord:
    """
    Core calculation engine:
    1. Validates employee and period eligibility.
    2. Takes immutable snapshots of employee metadata.
    3. Aggregates default active allowances, bonuses, and deductions.
    4. Evaluates approved KPI scores and calculates performance bonus.
    5. Evaluates approved manual adjustments.
    6. Computes taxable gross and applies active tax rules.
    7. Creates itemized PayrollLine entries.
    8. Updates PayrollRecord with exact Decimal precision.
    """
    if period.status in [PayrollPeriod.Status.APPROVED, PayrollPeriod.Status.CLOSED, PayrollPeriod.Status.CANCELLED]:
        raise ValidationError(_('Cannot calculate payroll for an approved, closed, or cancelled period.'))

    # Retrieve valid salary profile
    salary_profile = (
        SalaryProfile.objects
        .filter(user=employee, status=SalaryProfile.Status.ACTIVE, effective_from__lte=period.end_date)
        .order_by('-effective_from')
        .first()
    )
    if not salary_profile:
        # Fallback to latest profile if none specifically matches effective_from bounds
        salary_profile = SalaryProfile.objects.filter(user=employee, status=SalaryProfile.Status.ACTIVE).first()

    if not salary_profile:
        raise ValidationError(
            _('No active salary profile found for %(user)s.') % {'user': employee.display_name}
        )

    base_salary = quantize_money(salary_profile.base_salary)
    currency = salary_profile.currency

    # Snapshot organizational identity
    emp_name = employee.display_name
    emp_username = employee.username
    dept_name = employee.department.name if employee.department else ''
    pos_name = employee.position.name if employee.position else ''
    grade_name = f"{employee.grade.name} ({employee.grade.code})" if employee.grade else ''

    # Get or create master PayrollRecord
    record, created = PayrollRecord.objects.select_for_update().get_or_create(
        period=period,
        employee=employee,
        defaults={
            'employee_name_snapshot': emp_name,
            'employee_username_snapshot': emp_username,
            'department_snapshot': dept_name,
            'position_snapshot': pos_name,
            'grade_snapshot': grade_name,
            'base_salary': base_salary,
            'gross_salary': base_salary,
            'net_salary': base_salary,
            'currency': currency,
            'status': PayrollRecord.Status.CALCULATED,
        },
    )

    # Refresh snapshots
    record.employee_name_snapshot = emp_name
    record.employee_username_snapshot = emp_username
    record.department_snapshot = dept_name
    record.position_snapshot = pos_name
    record.grade_snapshot = grade_name
    record.base_salary = base_salary
    record.currency = currency

    # Clear previous calculated lines (if recalculating draft/calculated record)
    record.lines.all().delete()

    total_allowances = Decimal('0.00')
    total_bonuses = Decimal('0.00')
    total_deductions = Decimal('0.00')
    taxable_allowances = Decimal('0.00')
    lines_to_create = []

    # 1. Base Salary Line
    lines_to_create.append(
        PayrollLine(
            payroll=record,
            name_snapshot=_('Base Salary'),
            component_type=CompensationComponent.ComponentType.ALLOWANCE,
            calculation_type=CompensationComponent.CalculationType.FIXED,
            rate_or_value=base_salary,
            amount=base_salary,
            taxable=True,
            description=_('Contracted base salary'),
        )
    )

    # 2. Standard Active Compensation Components
    active_components = CompensationComponent.objects.filter(is_active=True)
    for comp in active_components:
        if comp.calculation_type == CompensationComponent.CalculationType.PERCENTAGE:
            amount = quantize_money((base_salary * comp.default_value) / Decimal('100.00'))
        else:
            amount = quantize_money(comp.default_value)

        if amount <= Decimal('0.00'):
            continue

        if comp.component_type == CompensationComponent.ComponentType.ALLOWANCE:
            total_allowances += amount
            if comp.is_taxable:
                taxable_allowances += amount
        elif comp.component_type == CompensationComponent.ComponentType.BONUS:
            total_bonuses += amount
        elif comp.component_type == CompensationComponent.ComponentType.DEDUCTION:
            total_deductions += amount

        lines_to_create.append(
            PayrollLine(
                payroll=record,
                component=comp,
                name_snapshot=comp.name,
                component_type=comp.component_type,
                calculation_type=comp.calculation_type,
                rate_or_value=comp.default_value,
                amount=amount,
                taxable=comp.is_taxable,
                description=comp.description or comp.name,
            )
        )

    # 3. Approved Manual Adjustments
    approved_adjustments = PayrollAdjustment.objects.filter(
        employee=employee,
        status=PayrollAdjustment.Status.APPROVED,
    ).filter(
        # Either tied to this record or matching period
        models.Q(payroll=record) | models.Q(period=period) | models.Q(period__isnull=True, payroll__isnull=True)
    )

    for adj in approved_adjustments:
        adj_amount = quantize_money(adj.amount)
        if adj.type in [PayrollAdjustment.AdjustmentType.BONUS, PayrollAdjustment.AdjustmentType.CORRECTION]:
            if adj_amount > Decimal('0.00'):
                total_bonuses += adj_amount
                comp_type = CompensationComponent.ComponentType.BONUS
            else:
                total_deductions += abs(adj_amount)
                comp_type = CompensationComponent.ComponentType.DEDUCTION
        elif adj.type == PayrollAdjustment.AdjustmentType.ALLOWANCE:
            total_allowances += adj_amount
            comp_type = CompensationComponent.ComponentType.ALLOWANCE
        elif adj.type == PayrollAdjustment.AdjustmentType.DEDUCTION:
            total_deductions += adj_amount
            comp_type = CompensationComponent.ComponentType.DEDUCTION

        lines_to_create.append(
            PayrollLine(
                payroll=record,
                name_snapshot=f"Adjustment: {adj.get_type_display()}",
                component_type=comp_type,
                calculation_type=CompensationComponent.CalculationType.FIXED,
                rate_or_value=adj_amount,
                amount=abs(adj_amount),
                taxable=True,
                description=adj.reason,
            )
        )
        # Link adjustment directly to this record
        if not adj.payroll:
            adj.payroll = record
            adj.save(update_fields=['payroll'])

    # 4. KPI Performance Bonus Calculation
    # Strictly query FINALIZED, RECTOR-SIGNED or CLOSED KPI results for this employee
    kpi_score = Decimal('0.00')
    kpi_evidence_data = {}
    signed_kpi_results = KPIResult.objects.filter(
        assignment__user=employee,
        assignment__period__status__in=[KPIPeriod.Status.RECTOR_SIGNED, KPIPeriod.Status.CLOSED],
        status__in=[KPIResult.Status.APPROVED, KPIResult.Status.LOCKED],
    )
    # Filter by code, date overlap, or latest signed/closed KPI period ending on or before payroll period
    period_kpi_results = signed_kpi_results.filter(
        models.Q(assignment__period__code=period.code) |
        models.Q(
            assignment__period__start_date__lte=period.end_date,
            assignment__period__end_date__gte=period.start_date,
        ) |
        models.Q(
            assignment__period__end_date__lte=period.end_date,
            assignment__period__end_date__gte=period.start_date - timezone.timedelta(days=95),
        )
    ).order_by('-assignment__period__end_date')
    if period_kpi_results.exists():
        matched_kpi_period = period_kpi_results.first().assignment.period
        period_kpi_results = period_kpi_results.filter(assignment__period=matched_kpi_period)
        kpi_score = sum(r.weighted_score for r in period_kpi_results)
        matched_kpi_period = period_kpi_results.first().assignment.period
        kpi_evidence_data = {
            'period_id': str(matched_kpi_period.id),
            'period_code': matched_kpi_period.code,
            'period_status': matched_kpi_period.status,
            'signed_by': matched_kpi_period.signed_by.display_name if matched_kpi_period.signed_by else None,
            'signed_at': matched_kpi_period.signed_at.isoformat() if matched_kpi_period.signed_at else None,
            'score': str(kpi_score),
            'results_count': period_kpi_results.count(),
        }

    kpi_score = quantize_money(kpi_score)
    kpi_bonus = Decimal('0.00')

    if kpi_score > Decimal('0.00'):
        rule = (
            KPIPayrollRule.objects
            .filter(is_active=True, min_score__lte=kpi_score, max_score__gte=kpi_score)
            .order_by('-max_score')
            .first()
        )
        if rule:
            if rule.bonus_type == KPIPayrollRule.BonusType.PERCENTAGE:
                kpi_bonus = quantize_money((base_salary * rule.bonus_value) / Decimal('100.00'))
            else:
                kpi_bonus = quantize_money(rule.bonus_value)

            desc_period = kpi_evidence_data.get('period_code', period.code)
            lines_to_create.append(
                PayrollLine(
                    payroll=record,
                    name_snapshot=f"KPI Bonus ({kpi_score} pts — {rule.name})",
                    component_type=CompensationComponent.ComponentType.BONUS,
                    calculation_type=rule.bonus_type,
                    rate_or_value=rule.bonus_value,
                    amount=kpi_bonus,
                    taxable=True,
                    description=_(
                        'Performance incentive derived from signed KPI period {period} (Score: {score} pts).'
                    ).format(period=desc_period, score=kpi_score),
                )
            )

    # 5. Gross Salary
    gross_salary = quantize_money(base_salary + total_allowances + total_bonuses + kpi_bonus)

    # 6. Tax Calculation Engine
    taxable_gross = quantize_money(base_salary + taxable_allowances + total_bonuses + kpi_bonus)
    total_tax = Decimal('0.00')

    active_tax_rules = PayrollTaxRule.objects.filter(
        is_active=True,
        effective_from__lte=period.end_date,
    )
    for tax_rule in active_tax_rules:
        if tax_rule.applies_to == PayrollTaxRule.AppliesTo.GROSS:
            base_amt = gross_salary
        elif tax_rule.applies_to == PayrollTaxRule.AppliesTo.BASE_SALARY:
            base_amt = base_salary
        else:
            base_amt = taxable_gross

        tax_amt = quantize_money((base_amt * tax_rule.percentage) / Decimal('100.00')) + quantize_money(tax_rule.fixed_amount)
        if tax_amt > Decimal('0.00'):
            total_tax += tax_amt
            lines_to_create.append(
                PayrollLine(
                    payroll=record,
                    name_snapshot=f"Tax: {tax_rule.name}",
                    component_type=CompensationComponent.ComponentType.DEDUCTION,
                    calculation_type=CompensationComponent.CalculationType.PERCENTAGE,
                    rate_or_value=tax_rule.percentage,
                    amount=tax_amt,
                    taxable=False,
                    description=tax_rule.code,
                )
            )

    # 7. Net Salary
    net_salary = quantize_money(gross_salary - total_deductions - total_tax)
    if net_salary < Decimal('0.00'):
        net_salary = Decimal('0.00')

    # Bulk create line items
    PayrollLine.objects.bulk_create(lines_to_create)

    # Save finalized calculations
    record.total_allowances = total_allowances
    record.total_bonuses = total_bonuses
    record.kpi_bonus = kpi_bonus
    record.total_deductions = total_deductions
    record.gross_salary = gross_salary
    record.tax_total = total_tax
    record.net_salary = net_salary
    record.kpi_score_snapshot = kpi_score
    record.status = PayrollRecord.Status.CALCULATED
    record.calculated_at = timezone.now()
    record.save()

    # Audit Log
    log_audit(
        actor=actor,
        action=AuditLog.Actions.PAYROLL_CALCULATED,
        target_repr=f"Payroll {record.employee_name_snapshot} ({period.code})",
        details={
            'record_id': str(record.id),
            'period': period.code,
            'employee_id': str(employee.id),
            'gross_salary': float(gross_salary),
            'net_salary': float(net_salary),
            'kpi_score': float(kpi_score),
            'kpi_bonus': float(kpi_bonus),
        },
        request=request,
    )

    return record


@transaction.atomic
def calculate_period_payroll(
    period: PayrollPeriod,
    actor: User = None,
    request=None,
) -> int:
    """Calculates payroll for all active employees for the given period."""
    if period.status in [PayrollPeriod.Status.APPROVED, PayrollPeriod.Status.CLOSED, PayrollPeriod.Status.CANCELLED]:
        raise ValidationError(_('Period is locked and cannot be recalculated.'))

    period.status = PayrollPeriod.Status.CALCULATING
    period.save(update_fields=['status'])

    # Find all active employees who have an active salary profile
    eligible_users = User.objects.filter(
        is_active=True,
        salary_profiles__status=SalaryProfile.Status.ACTIVE,
    ).distinct()

    count = 0
    for user in eligible_users:
        calculate_payroll(user, period, actor=actor, request=request)
        count += 1

    period.status = PayrollPeriod.Status.PENDING_APPROVAL
    period.save(update_fields=['status'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.PAYROLL_PERIOD_OPENED,
        target_repr=f"Payroll Period {period.code}",
        details={'period': period.code, 'records_calculated': count},
        request=request,
    )

    return count


# ---------------------------------------------------------------------------
# 3. Approval & Disbursement Workflow
# ---------------------------------------------------------------------------

@transaction.atomic
def approve_payroll_record(actor: User, record: PayrollRecord, request=None) -> PayrollRecord:
    """Approves an individual employee payroll record, locking it against edits."""
    if record.status in [PayrollRecord.Status.APPROVED, PayrollRecord.Status.PAID]:
        return record

    record.status = PayrollRecord.Status.APPROVED
    record.approved_at = timezone.now()
    record.approved_by = actor
    record.payment_status = PayrollRecord.PaymentStatus.READY
    record.save(update_fields=['status', 'approved_at', 'approved_by', 'payment_status'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.PAYROLL_APPROVED,
        target_repr=f"Payroll Approved: {record.employee_name_snapshot} ({record.period.code})",
        details={'record_id': str(record.id), 'net_salary': float(record.net_salary)},
        request=request,
    )

    Notification.objects.create(
        recipient=record.employee,
        notification_type=Notification.NotificationType.PAYROLL_APPROVED,
        title=_('Payroll Approved'),
        message=_(
            'Your payroll for %(period)s (Net: %(net)s %(currency)s) has been approved and authorized.'
        ) % {
            'period': record.period.name,
            'net': f"{record.net_salary:,.2f}",
            'currency': record.currency,
        },
    )

    return record


@transaction.atomic
def approve_period_payroll(actor: User, period: PayrollPeriod, request=None) -> int:
    """Approves all pending records in a period and locks the period."""
    records = period.records.filter(status=PayrollRecord.Status.CALCULATED)
    count = 0
    for rec in records:
        approve_payroll_record(actor, rec, request=request)
        count += 1

    period.status = PayrollPeriod.Status.APPROVED
    period.approved_at = timezone.now()
    period.approved_by = actor
    period.save(update_fields=['status', 'approved_at', 'approved_by'])

    return count


@transaction.atomic
def mark_payroll_paid(
    actor: User,
    record: PayrollRecord,
    payment_reference: str = '',
    request=None,
) -> PayrollRecord:
    """Marks an approved payroll record as disbursed/paid."""
    if record.status not in [PayrollRecord.Status.APPROVED, PayrollRecord.Status.PAID]:
        raise ValidationError(_('Payroll must be approved before marking as paid.'))

    record.payment_status = PayrollRecord.PaymentStatus.PAID
    record.status = PayrollRecord.Status.PAID
    record.paid_at = timezone.now()
    record.paid_by = actor
    record.payment_reference = payment_reference
    record.save(update_fields=['payment_status', 'status', 'paid_at', 'paid_by', 'payment_reference'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.PAYROLL_PAID,
        target_repr=f"Payroll Disbursed: {record.employee_name_snapshot}",
        details={
            'record_id': str(record.id),
            'payment_reference': payment_reference,
            'amount': float(record.net_salary),
        },
        request=request,
    )

    Notification.objects.create(
        recipient=record.employee,
        notification_type=Notification.NotificationType.PAYROLL_PAID,
        title=_('Salary Disbursed'),
        message=_(
            'Your payment of %(net)s %(currency)s for %(period)s has been disbursed. Ref: %(ref)s'
        ) % {
            'net': f"{record.net_salary:,.2f}",
            'currency': record.currency,
            'period': record.period.name,
            'ref': payment_reference or _('Bank Transfer'),
        },
    )

    return record


@transaction.atomic
def close_payroll_period(actor: User, period: PayrollPeriod, request=None) -> PayrollPeriod:
    """Closes and finalizes a payroll period after all disbursements."""
    period.status = PayrollPeriod.Status.CLOSED
    period.closed_at = timezone.now()
    period.closed_by = actor
    period.save(update_fields=['status', 'closed_at', 'closed_by'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.PAYROLL_CLOSED,
        target_repr=f"Payroll Period Closed: {period.code}",
        details={'period': period.code},
        request=request,
    )

    return period


@transaction.atomic
def configure_payroll_authority(actor: User, target_user: User, permissions_data: dict, request=None):
    """Configures granular payroll permissions for a user (Rector or Superadmin only)."""
    if not (actor.is_superuser or actor.is_rector):
        raise PermissionDenied(_('Only the Rector or Technical Superadmin can configure payroll authority permissions.'))

    from payroll.models import PayrollPermissionConfig
    config, _ = PayrollPermissionConfig.objects.get_or_create(user=target_user)

    for field in [
        'can_view_payroll',
        'can_manage_salary',
        'can_manage_compensation',
        'can_calculate_payroll',
        'can_create_adjustment',
        'can_approve_payroll',
        'can_mark_paid',
        'can_view_payroll_reports',
        'can_manage_tax_rules',
        'can_manage_kpi_payroll_rules',
    ]:
        if field in permissions_data:
            setattr(config, field, bool(permissions_data[field]))

    config.save()

    log_audit(
        actor=actor,
        action=AuditLog.Actions.PAYROLL_PERMISSION_CHANGED,
        target_repr=f"Payroll Authority -> {target_user.display_name}",
        details={'user': target_user.username, 'permissions': permissions_data},
        request=request,
    )
    return config

