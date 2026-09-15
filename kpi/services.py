import json
import secrets
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from core.models import AuditLog, Notification, create_notification, log_audit
from kpi.calculation import (
    calculate_deadline_compliance_metric,
    calculate_raw_score,
    calculate_task_completion_metric,
    normalize_period_weights,
    quantize_score,
    recalculate_employee_period_kpis,
)
from kpi.models import (
    KPIAssignment,
    KPICategory,
    KPICorrectionRequest,
    KPIDefinition,
    KPIPeriod,
    KPIResult,
    KPISnapshot,
)
from organization.models import Department
from signatures.crypto import (
    SignatureKeyProvider,
    canonical_json,
    compute_sha256,
    sign_data,
)
from signatures.models import ElectronicSignature, SignatureSnapshot
from tasks.models import Task, TaskAssignment


def calculate_task_completion_rate(user: User, start_date=None, end_date=None) -> float:
    """Calculates percentage of assigned tasks successfully completed by the user."""
    metric = calculate_task_completion_metric(user, start_date, end_date)
    return float(metric['rate']) if metric['rate'] is not None else 0.0


def calculate_deadline_compliance_rate(user: User, start_date=None, end_date=None) -> float:
    """Calculates percentage of completed tasks finished on or before the authoritative deadline."""
    metric = calculate_deadline_compliance_metric(user, start_date, end_date)
    return float(metric['rate']) if metric['rate'] is not None else 0.0


def calculate_user_kpi_summary(user: User, period: KPIPeriod | None = None) -> dict[str, Any]:
    """
    Computes a transparent, explainable KPI summary and score breakdown for a specific user and period.
    """
    if not period:
        period = (
            KPIPeriod.objects.filter(
                is_active=True,
                status__in=[
                    KPIPeriod.Status.OPEN,
                    KPIPeriod.Status.UNDER_REVIEW,
                    KPIPeriod.Status.HR_VERIFIED,
                    KPIPeriod.Status.PENDING_RECTOR_APPROVAL,
                    KPIPeriod.Status.RECTOR_APPROVED,
                    KPIPeriod.Status.RECTOR_SIGNED,
                ],
            ).first()
            or KPIPeriod.objects.filter(is_active=True).first()
        )

    if period and not period.is_immutable:
        # Dynamically evaluate automated indicators for open periods
        recalculate_employee_period_kpis(user, period)

    assignments_qs = (
        KPIAssignment.objects.filter(user=user, is_active=True)
        .select_related('kpi', 'kpi__category')
    )
    if period:
        assignments_qs = assignments_qs.filter(period=period)

    assignments = list(assignments_qs)
    total_assigned_weight = sum(a.normalized_weight for a in assignments)
    total_weighted_score = Decimal('0.00')

    breakdown = []
    for assign in assignments:
        result = getattr(assign, 'result', None)
        if result:
            actual = result.actual_value
            raw_score = result.raw_score
            weighted = result.weighted_score
            configured_w = result.configured_weight or assign.configured_weight
            normalized_w = result.normalized_weight or assign.normalized_weight
            status = result.get_status_display()
            evidence = result.calculation_evidence or {}
        else:
            actual = Decimal('0.00')
            raw_score = Decimal('0.00')
            weighted = Decimal('0.00')
            configured_w = assign.configured_weight
            normalized_w = assign.normalized_weight
            status = _('Not Recorded')
            evidence = {}

        total_weighted_score += weighted
        breakdown.append({
            'assignment_id': assign.id,
            'kpi_name': assign.kpi.name,
            'category': assign.kpi.category.name,
            'measurement_type': assign.kpi.get_measurement_type_display(),
            'source_type': assign.kpi.get_source_type_display(),
            'target_value': assign.target_value,
            'actual_value': actual,
            'configured_weight': configured_w,
            'normalized_weight': normalized_w,
            'weight': normalized_w,
            'raw_score': raw_score,
            'weighted_score': weighted,
            'status': status,
            'has_result': result is not None,
            'evidence': evidence,
        })

    # Task metrics for this period
    start = period.start_date if period else None
    end = period.end_date if period else None
    task_metric = calculate_task_completion_metric(user, start, end)
    deadline_metric = calculate_deadline_compliance_metric(user, start, end)

    task_assignments = TaskAssignment.objects.filter(user=user)
    if start:
        task_assignments = task_assignments.filter(task__created_at__date__gte=start)
    if end:
        task_assignments = task_assignments.filter(task__created_at__date__lte=end)

    return {
        'user': user,
        'period': period,
        'total_score': float(quantize_score(total_weighted_score)),
        'total_assigned_weight': float(quantize_score(total_assigned_weight)),
        'breakdown': breakdown,
        'task_completion_rate': float(task_metric['rate']) if task_metric['rate'] is not None else 0.0,
        'deadline_compliance_rate': float(deadline_metric['rate']) if deadline_metric['rate'] is not None else 0.0,
        'total_tasks': task_metric['eligible_count'],
        'completed_tasks': task_metric['completed_count'],
        'active_tasks': task_assignments.filter(task__status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]).count(),
    }


def calculate_department_kpi_summary(department: Department, period: KPIPeriod | None = None) -> dict[str, Any]:
    """
    Aggregates department-level performance metrics, employee scores, and task metrics.
    Mathematically consistent: does NOT exclude poor-performing staff or departments with 0 score.
    """
    if not period:
        period = (
            KPIPeriod.objects.filter(
                is_active=True,
                status__in=[
                    KPIPeriod.Status.OPEN,
                    KPIPeriod.Status.UNDER_REVIEW,
                    KPIPeriod.Status.HR_VERIFIED,
                    KPIPeriod.Status.RECTOR_SIGNED,
                ],
            ).first()
            or KPIPeriod.objects.filter(is_active=True).first()
        )

    employees = department.users.filter(is_active=True).select_related('position', 'grade')
    employee_summaries = []
    total_scores = []

    for emp in employees:
        summary = calculate_user_kpi_summary(emp, period)
        employee_summaries.append({
            'user': emp,
            'position': emp.position.name if emp.position else '—',
            'grade': emp.grade.code if emp.grade else '—',
            'kpi_score': summary['total_score'],
            'completed_tasks': summary['completed_tasks'],
            'completion_rate': summary['task_completion_rate'],
        })
        if summary['breakdown']:
            total_scores.append(summary['total_score'])

    avg_score = round(sum(total_scores) / len(total_scores), 1) if total_scores else 0.0

    # Department tasks
    dept_tasks = Task.objects.filter(responsible_department=department)
    if period:
        dept_tasks = dept_tasks.filter(created_at__date__gte=period.start_date, created_at__date__lte=period.end_date)

    total_tasks = dept_tasks.exclude(status=Task.Status.CANCELLED).count()
    completed_tasks = dept_tasks.filter(status=Task.Status.COMPLETED).count()
    dept_completion_rate = round((completed_tasks / total_tasks) * 100.0, 1) if total_tasks > 0 else 0.0

    return {
        'department': department,
        'period': period,
        'headcount': employees.count(),
        'evaluated_headcount': len(total_scores),
        'avg_kpi_score': avg_score,
        'employees': employee_summaries,
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'task_completion_rate': dept_completion_rate,
    }


def calculate_vice_rector_kpi_summary(vice_rector: User, period: KPIPeriod | None = None) -> dict[str, Any]:
    """
    Aggregates performance across all departments supervised by the Vice Rector.
    """
    scoped_depts = vice_rector.get_scoped_departments()
    dept_summaries = []
    all_scores = []

    for dept in scoped_depts:
        summary = calculate_department_kpi_summary(dept, period)
        dept_summaries.append(summary)
        all_scores.append(summary['avg_kpi_score'])

    overall_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    return {
        'vice_rector': vice_rector,
        'period': period,
        'supervised_departments_count': scoped_depts.count(),
        'overall_score': overall_avg,
        'departments': dept_summaries,
    }


def calculate_university_kpi_summary(period: KPIPeriod | None = None) -> dict[str, Any]:
    """
    Aggregates university-wide performance across all departments and employees.
    """
    if not period:
        period = (
            KPIPeriod.objects.filter(
                is_active=True,
                status__in=[
                    KPIPeriod.Status.OPEN,
                    KPIPeriod.Status.UNDER_REVIEW,
                    KPIPeriod.Status.HR_VERIFIED,
                    KPIPeriod.Status.RECTOR_SIGNED,
                ],
            ).first()
            or KPIPeriod.objects.filter(is_active=True).first()
        )

    departments = Department.objects.filter(is_active=True)
    dept_summaries = []
    all_dept_scores = []

    for dept in departments:
        summary = calculate_department_kpi_summary(dept, period)
        dept_summaries.append(summary)
        all_dept_scores.append(summary['avg_kpi_score'])

    univ_avg = round(sum(all_dept_scores) / len(all_dept_scores), 1) if all_dept_scores else 0.0

    all_tasks = Task.objects.all().exclude(status=Task.Status.CANCELLED)
    if period:
        all_tasks = all_tasks.filter(created_at__date__gte=period.start_date, created_at__date__lte=period.end_date)
    total_t = all_tasks.count()
    completed_t = all_tasks.filter(status=Task.Status.COMPLETED).count()

    return {
        'period': period,
        'university_avg_score': univ_avg,
        'total_departments': departments.count(),
        'departments': dept_summaries,
        'total_tasks': total_t,
        'completed_tasks': completed_t,
        'task_completion_rate': round((completed_t / total_t) * 100.0, 1) if total_t > 0 else 0.0,
    }


@transaction.atomic
def record_kpi_result(
    actor: User,
    assignment: KPIAssignment,
    actual_value: Decimal | float,
    notes: str = '',
    request=None,
) -> KPIResult:
    """
    Records or updates an actual KPI evaluation result.
    Enforces period immutability and recalculates raw and weighted scores.
    """
    if assignment.period.is_immutable:
        raise PermissionDenied(_('Cannot record or modify evaluations in a locked or signed KPI period.'))

    actual_dec = Decimal(str(actual_value))
    target_dec = assignment.target_value
    kpi = assignment.kpi

    raw_score = calculate_raw_score(
        actual_val=actual_dec,
        target_val=target_dec,
        measurement_type=kpi.measurement_type,
        direction=kpi.direction,
        min_val=kpi.min_value,
        max_val=kpi.max_value,
        no_data_policy=kpi.no_data_policy,
        has_data=True,
    )
    if raw_score is None:
        raw_score = Decimal('0.00')

    norm_weight = assignment.normalized_weight or assignment.configured_weight
    weighted_score = quantize_score((raw_score * norm_weight) / Decimal('100.00'))

    result, _ = KPIResult.objects.get_or_create(assignment=assignment)
    if result.is_locked:
        raise PermissionDenied(_('This KPI result is locked and cannot be edited.'))

    result.actual_value = actual_dec
    result.raw_score = raw_score
    result.configured_weight = assignment.configured_weight
    result.normalized_weight = norm_weight
    result.weighted_score = weighted_score
    result.status = (
        KPIResult.Status.REVIEWED
        if (actor.is_superuser or actor.is_rector or actor.is_hr)
        else KPIResult.Status.SUBMITTED
    )
    result.notes = notes
    result.evaluated_by = actor
    result.evaluated_at = timezone.now()
    result.calculation_evidence = {
        'source': 'MANUAL_EVALUATION',
        'evaluator_id': str(actor.id),
        'evaluator_name': actor.display_name,
        'notes': notes,
        'recorded_at': timezone.now().isoformat(),
    }
    result.save()

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_RESULT_RECORDED,
        target_repr=f"{assignment.user.display_name} -> {kpi.name}",
        details={
            'actual_value': str(actual_dec),
            'raw_score': str(raw_score),
            'weighted_score': str(weighted_score),
            'period': assignment.period.code,
        },
        request=request,
    )
    return result


@transaction.atomic
def approve_kpi_result(actor: User, result: KPIResult, request=None) -> KPIResult:
    """Approves an individual KPI evaluation result."""
    if result.assignment.period.is_immutable or result.is_locked:
        raise PermissionDenied(_('Cannot approve an evaluation in a locked or signed KPI period.'))

    result.status = KPIResult.Status.APPROVED
    result.evaluated_by = actor
    result.evaluated_at = timezone.now()
    result.save(update_fields=['status', 'evaluated_by', 'evaluated_at', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_RESULT_APPROVED,
        target_repr=f"{result.assignment.user.display_name} -> {result.assignment.kpi.name}",
        details={'weighted_score': str(result.weighted_score)},
        request=request,
    )
    return result


# ===========================================================================
# PERIOD LIFECYCLE & RECTOR APPROVAL WORKFLOW
# ===========================================================================

@transaction.atomic
def calculate_kpi_period(actor: User, period: KPIPeriod, request=None) -> dict[str, Any]:
    """
    Executes centralized automatic calculation across all employees in the period.
    Moves status from OPEN -> CALCULATING -> UNDER_REVIEW.
    """
    if period.is_immutable:
        raise PermissionDenied(_('Cannot calculate a closed or signed KPI period.'))

    period.status = KPIPeriod.Status.CALCULATING
    period.save(update_fields=['status', 'updated_at'])

    assigned_users = User.objects.filter(
        kpi_assignments__period=period, kpi_assignments__is_active=True
    ).distinct()

    total_evaluated = 0
    for u in assigned_users:
        recalculate_employee_period_kpis(u, period, actor=actor)
        total_evaluated += 1

    period.status = KPIPeriod.Status.UNDER_REVIEW
    period.save(update_fields=['status', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_CALCULATED,
        target_repr=f"Period {period.code} Evaluated ({total_evaluated} staff)",
        details={'period': period.code, 'total_staff': total_evaluated},
        request=request,
    )

    return {'total_evaluated': total_evaluated, 'period': period}


@transaction.atomic
def hr_verify_kpi_period(actor: User, period: KPIPeriod, notes: str = '', request=None) -> KPIPeriod:
    """
    HR verifies evaluation completeness and prepares the KPI package for executive approval.
    Moves status to HR_VERIFIED.
    """
    if not (actor.is_superuser or actor.is_rector or actor.is_hr):
        raise PermissionDenied(_('Only HR or Executive authorities can verify KPI periods.'))
    if period.is_immutable:
        raise PermissionDenied(_('Cannot verify a locked or closed KPI period.'))

    period.status = KPIPeriod.Status.HR_VERIFIED
    period.save(update_fields=['status', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_VERIFIED,
        target_repr=f"Period {period.code} Verified by HR",
        details={'notes': notes},
        request=request,
    )

    # Notify Rector
    rector_user = User.objects.filter(roles__code='RECTOR', is_active=True).first()
    if rector_user:
        create_notification(
            recipient=rector_user,
            notification_type=Notification.NotificationType.KPI_HR_VERIFIED,
            title=_('KPI Period Verified by HR'),
            message=_('KPI Period {period} has been verified by HR and is awaiting executive review.').format(
                period=period.name
            ),
            link=f"/performance/periods/{period.id}/rector-review/",
        )

    return period


@transaction.atomic
def submit_kpi_period_for_rector(actor: User, period: KPIPeriod, request=None) -> KPIPeriod:
    """Submits the verified period to Rector for final executive review."""
    if not (actor.is_superuser or actor.is_rector or actor.is_hr):
        raise PermissionDenied(_('You do not have permission to submit KPI periods to Rector.'))
    if period.is_immutable:
        raise PermissionDenied(_('Cannot submit a locked or closed KPI period.'))

    period.status = KPIPeriod.Status.PENDING_RECTOR_APPROVAL
    period.save(update_fields=['status', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_SUBMITTED_FOR_RECTOR,
        target_repr=f"Period {period.code} Submitted for Rector Approval",
        details={},
        request=request,
    )
    return period


@transaction.atomic
def rector_approve_kpi_period(actor: User, period: KPIPeriod, notes: str = '', request=None) -> KPIPeriod:
    """
    Rector approves the KPI period. Once approved, the period becomes eligible for Ed25519 signing.
    """
    if not (actor.is_superuser or actor.is_rector):
        raise PermissionDenied(_('Only the Rector can approve a university KPI period.'))
    if period.is_immutable:
        raise PermissionDenied(_('Cannot approve a locked or closed KPI period.'))

    period.status = KPIPeriod.Status.RECTOR_APPROVED
    period.approved_by = actor
    period.rejection_reason = ''
    period.save(update_fields=['status', 'approved_by', 'rejection_reason', 'updated_at'])

    # Approve all unapproved results in this period
    KPIResult.objects.filter(assignment__period=period).update(
        status=KPIResult.Status.APPROVED,
        evaluated_by=actor,
        evaluated_at=timezone.now(),
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_RECTOR_APPROVED,
        target_repr=f"Period {period.code} Approved by Rector",
        details={'notes': notes},
        request=request,
    )

    return period


@transaction.atomic
def rector_reject_kpi_period(actor: User, period: KPIPeriod, reason: str, request=None) -> KPIPeriod:
    """
    Rector rejects the KPI period with a mandatory explanation reason.
    Returns period to UNDER_REVIEW state for corrective review.
    """
    if not (actor.is_superuser or actor.is_rector):
        raise PermissionDenied(_('Only the Rector can reject a university KPI period.'))
    if not reason or not reason.strip():
        raise ValidationError({'reason': _('A rejection reason is strictly mandatory.')})

    period.status = KPIPeriod.Status.UNDER_REVIEW
    period.rejection_reason = reason
    period.save(update_fields=['status', 'rejection_reason', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_RECTOR_REJECTED,
        target_repr=f"Period {period.code} Rejected by Rector",
        details={'reason': reason},
        request=request,
    )

    # Notify HR managers
    hr_users = User.objects.filter(roles__code='HR', is_active=True)
    for hr in hr_users:
        create_notification(
            recipient=hr,
            notification_type=Notification.NotificationType.KPI_RECTOR_REJECTED,
            title=_('KPI Period Rejected by Rector'),
            message=_('KPI Period {period} was rejected for revision. Reason: {reason}').format(
                period=period.code, reason=reason
            ),
            link=f"/performance/periods/",
        )

    return period


@transaction.atomic
def rector_sign_kpi_period(actor: User, period: KPIPeriod, request=None) -> ElectronicSignature:
    """
    Rector electronically signs the finalized university KPI period using existing Ed25519 cryptography.
    Enforces immutability: locks period and all constituent results.
    """
    if not (actor.is_superuser or actor.is_rector):
        raise PermissionDenied(_('Only the Rector can sign a university KPI period.'))
    if period.status != KPIPeriod.Status.RECTOR_APPROVED:
        raise ValidationError(_('KPI period must be Rector Approved before electronic signing.'))

    # 1. Build canonical package payload
    univ_summary = calculate_university_kpi_summary(period)
    dept_summaries_data = []
    for d in univ_summary['departments']:
        dept_summaries_data.append({
            'department_id': str(d['department'].id),
            'department_name': d['department'].name,
            'avg_score': d['avg_kpi_score'],
            'headcount': d['headcount'],
            'evaluated_headcount': d['evaluated_headcount'],
        })

    assignments_data = []
    for assign in period.assignments.filter(is_active=True).select_related('user', 'kpi', 'result'):
        res = getattr(assign, 'result', None)
        assignments_data.append({
            'assignment_id': str(assign.id),
            'employee_id': str(assign.user.id),
            'employee_name': assign.user.display_name,
            'kpi_code': assign.kpi.code,
            'kpi_name': assign.kpi.name,
            'target_value': str(assign.target_value),
            'actual_value': str(res.actual_value if res else '0.00'),
            'raw_score': str(res.raw_score if res else '0.00'),
            'normalized_weight': str(assign.normalized_weight),
            'weighted_score': str(res.weighted_score if res else '0.00'),
            'is_approved': res.status == KPIResult.Status.APPROVED if res else False,
        })

    canonical_payload = {
        'schema_version': 1,
        'package_type': 'UNIVERSITY_KPI_PERIOD',
        'period_id': str(period.id),
        'period_code': period.code,
        'period_name': period.name,
        'start_date': period.start_date.isoformat(),
        'end_date': period.end_date.isoformat(),
        'total_evaluated_employees': len(assignments_data),
        'university_avg_score': str(univ_summary['university_avg_score']),
        'department_summaries': dept_summaries_data,
        'employee_evaluations': assignments_data,
        'signer': {
            'signer_id': str(actor.id),
            'signer_username': actor.username,
            'signer_name': actor.display_name,
            'signer_position': actor.position.name if actor.position else '',
        },
        'approved_at': timezone.now().isoformat(),
    }

    canonical_bytes = canonical_json(canonical_payload)
    payload_hash = compute_sha256(canonical_bytes)
    snapshot_hash = payload_hash

    # 2. Asymmetric Ed25519 signing
    private_key = SignatureKeyProvider.get_active_private_key()
    public_key = SignatureKeyProvider.get_active_public_key()
    key_version = SignatureKeyProvider.get_key_version()
    public_pem = SignatureKeyProvider.export_public_key_pem(public_key)
    signature_val_b64 = sign_data(private_key, canonical_bytes)

    verification_id = f"SIG-{timezone.now().year}-{secrets.token_hex(6).upper()}"
    verification_token = secrets.token_hex(32)

    # 3. Create ElectronicSignature record
    signature = ElectronicSignature.objects.create(
        task=None,
        kpi_period=period,
        signer=actor,
        signature_type=ElectronicSignature.SignatureType.KPI_PERIOD_SIGNATURE,
        status=ElectronicSignature.Status.SIGNED,
        verification_id=verification_id,
        verification_token=verification_token,
        snapshot_hash=snapshot_hash,
        payload_hash=payload_hash,
        signature_value=signature_val_b64,
        algorithm='Ed25519',
        key_version=key_version,
        public_key_reference=public_pem,
        signed_at=timezone.now(),
    )

    # 4. Create SignatureSnapshot
    SignatureSnapshot.objects.create(
        signature=signature,
        canonical_payload=canonical_payload,
        payload_hash=payload_hash,
    )

    # 5. Create KPISnapshot
    KPISnapshot.objects.create(
        period=period,
        signature=signature,
        canonical_payload=canonical_payload,
        payload_hash=payload_hash,
        total_employees=len(assignments_data),
        average_score=Decimal(str(univ_summary['university_avg_score'])),
    )

    # 6. Lock Period & All Results
    period.status = KPIPeriod.Status.RECTOR_SIGNED
    period.signed_by = actor
    period.signed_at = timezone.now()
    period.save(update_fields=['status', 'signed_by', 'signed_at', 'updated_at'])

    KPIResult.objects.filter(assignment__period=period).update(
        is_locked=True,
        status=KPIResult.Status.LOCKED,
    )

    # 7. Audit Logging
    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_RECTOR_SIGNED,
        target_repr=f"Period {period.code} Signed by Rector ({verification_id})",
        details={'verification_id': verification_id, 'snapshot_hash': snapshot_hash},
        request=request,
    )
    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_LOCKED,
        target_repr=f"Period {period.code} Results Locked",
        details={'period': period.code},
        request=request,
    )

    return signature


@transaction.atomic
def close_kpi_period(actor: User, period: KPIPeriod, request=None) -> KPIPeriod:
    """Closes and archives a KPI period."""
    if not (actor.is_superuser or actor.is_rector):
        raise PermissionDenied(_('Only the Rector or Technical Superadmin can close a KPI period.'))

    period.status = KPIPeriod.Status.CLOSED
    period.approved_by = actor
    period.save(update_fields=['status', 'approved_by', 'updated_at'])

    # Ensure all results locked
    KPIResult.objects.filter(assignment__period=period).update(is_locked=True)

    log_audit(
        actor=actor,
        action=AuditLog.Actions.KPI_PERIOD_CLOSED,
        target_repr=f"Period {period.code} Closed",
        details={'period': period.code},
        request=request,
    )
    return period


# ===========================================================================
# CORRECTION REQUEST WORKFLOW
# ===========================================================================

@transaction.atomic
def request_kpi_correction(
    requester: User,
    result: KPIResult,
    requested_actual_value: Decimal | float,
    reason: str,
    evidence: str = '',
    request=None,
) -> KPICorrectionRequest:
    """Creates a transparent correction request for an evaluation."""
    req = KPICorrectionRequest.objects.create(
        result=result,
        requester=requester,
        requested_actual_value=Decimal(str(requested_actual_value)),
        reason=reason,
        evidence=evidence,
        status=KPICorrectionRequest.Status.REQUESTED,
    )

    log_audit(
        actor=requester,
        action=AuditLog.Actions.KPI_CORRECTION_REQUESTED,
        target_repr=f"Correction Request for {result.assignment}",
        details={'requested_value': str(requested_actual_value), 'reason': reason},
        request=request,
    )
    return req


@transaction.atomic
def rector_decide_kpi_correction(
    actor: User,
    correction: KPICorrectionRequest,
    approved: bool,
    decision_reason: str = '',
    request=None,
) -> KPICorrectionRequest:
    """Rector decides on a formal KPI correction request."""
    if not (actor.is_superuser or actor.is_rector):
        raise PermissionDenied(_('Only the Rector can approve or reject KPI corrections.'))

    if approved:
        correction.status = KPICorrectionRequest.Status.APPROVED
        correction.reviewed_by = actor
        correction.rector_decision_reason = decision_reason
        correction.save()

        # Update result version and score safely
        res = correction.result
        res.version += 1
        res.actual_value = correction.requested_actual_value
        raw = calculate_raw_score(
            actual_val=res.actual_value,
            target_val=res.assignment.target_value,
            measurement_type=res.assignment.kpi.measurement_type,
            direction=res.assignment.kpi.direction,
            min_val=res.assignment.kpi.min_value,
            max_val=res.assignment.kpi.max_value,
            no_data_policy=res.assignment.kpi.no_data_policy,
        )
        res.raw_score = raw if raw is not None else Decimal('0.00')
        res.weighted_score = quantize_score((res.raw_score * res.normalized_weight) / Decimal('100.00'))
        res.save()

        log_audit(
            actor=actor,
            action=AuditLog.Actions.KPI_CORRECTION_APPROVED,
            target_repr=f"Correction Approved for {res.assignment} (v{res.version})",
            details={'new_value': str(correction.requested_actual_value), 'reason': decision_reason},
            request=request,
        )
    else:
        correction.status = KPICorrectionRequest.Status.REJECTED
        correction.reviewed_by = actor
        correction.rector_decision_reason = decision_reason
        correction.save()

        log_audit(
            actor=actor,
            action=AuditLog.Actions.KPI_CORRECTION_REJECTED,
            target_repr=f"Correction Rejected for {correction.result.assignment}",
            details={'reason': decision_reason},
            request=request,
        )

    return correction
