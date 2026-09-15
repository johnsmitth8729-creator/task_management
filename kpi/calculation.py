from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import User
from kpi.models import KPIAssignment, KPIDefinition, KPIPeriod, KPIResult
from tasks.models import Task, TaskAssignment


def quantize_score(val: Decimal | float | int) -> Decimal:
    """Consistently rounds a score or percentage to 2 decimal places using standard ROUND_HALF_UP."""
    if val is None:
        return Decimal('0.00')
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_task_completion_metric(user: User, start_date=None, end_date=None) -> dict[str, Any]:
    """
    Calculates percentage of eligible tasks completed by the user.
    Rules:
    - Only tasks where user is assigned are considered.
    - Management-cancelled tasks are excluded from the denominator.
    - Completed tasks require task.status == COMPLETED and assignment.assignment_status == APPROVED.
    - Distinguishes 0 measurable tasks (has_data=False) from 0% completion.
    """
    assignments = TaskAssignment.objects.filter(user=user).select_related('task')
    if start_date:
        assignments = assignments.filter(task__created_at__date__gte=start_date)
    if end_date:
        assignments = assignments.filter(task__created_at__date__lte=end_date)

    # Exclude management-cancelled tasks from denominator
    eligible_assignments = assignments.exclude(task__status=Task.Status.CANCELLED)
    total_eligible = eligible_assignments.count()

    if total_eligible == 0:
        return {
            'has_data': False,
            'rate': None,
            'eligible_count': 0,
            'completed_count': 0,
            'evidence_tasks': [],
        }

    completed_assignments = eligible_assignments.filter(
        assignment_status=TaskAssignment.AssignmentStatus.APPROVED,
        task__status=Task.Status.COMPLETED,
    )
    completed_count = completed_assignments.count()
    rate = quantize_score((Decimal(completed_count) / Decimal(total_eligible)) * Decimal('100.00'))

    evidence_tasks = []
    for a in eligible_assignments[:25]:
        evidence_tasks.append({
            'task_id': str(a.task.id),
            'task_number': a.task.task_number,
            'title': a.task.title,
            'status': a.task.status,
            'assignment_status': a.assignment_status,
            'completed_at': a.task.completed_at.isoformat() if a.task.completed_at else None,
            'is_completed': a.task.status == Task.Status.COMPLETED and a.assignment_status == TaskAssignment.AssignmentStatus.APPROVED,
        })

    return {
        'has_data': True,
        'rate': rate,
        'eligible_count': total_eligible,
        'completed_count': completed_count,
        'evidence_tasks': evidence_tasks,
    }


def calculate_deadline_compliance_metric(user: User, start_date=None, end_date=None) -> dict[str, Any]:
    """
    Calculates percentage of completed tasks delivered on or before the authoritative deadline.
    Rules:
    - Uses task.completed_at as authoritative finish timestamp (NEVER task.updated_at).
    - Checks against task.deadline (which holds the latest approved deadline, including extensions).
    - Distinguishes 0 completed tasks (has_data=False) from 0% on-time delivery.
    """
    completed_assignments = TaskAssignment.objects.filter(
        user=user,
        assignment_status=TaskAssignment.AssignmentStatus.APPROVED,
        task__status=Task.Status.COMPLETED,
    ).select_related('task')

    if start_date:
        completed_assignments = completed_assignments.filter(task__created_at__date__gte=start_date)
    if end_date:
        completed_assignments = completed_assignments.filter(task__created_at__date__lte=end_date)

    total_completed = completed_assignments.count()
    if total_completed == 0:
        return {
            'has_data': False,
            'rate': None,
            'completed_count': 0,
            'ontime_count': 0,
            'late_count': 0,
            'evidence_tasks': [],
        }

    ontime_count = 0
    late_count = 0
    evidence_tasks = []

    for a in completed_assignments:
        task = a.task
        # Authoritative completion date: task.completed_at
        finish_date = task.completed_at.date() if task.completed_at else task.updated_at.date()
        effective_deadline = task.deadline

        is_ontime = True
        if effective_deadline:
            if finish_date <= effective_deadline:
                ontime_count += 1
                is_ontime = True
            else:
                late_count += 1
                is_ontime = False
        else:
            ontime_count += 1
            is_ontime = True

        evidence_tasks.append({
            'task_id': str(task.id),
            'task_number': task.task_number,
            'title': task.title,
            'finish_date': finish_date.isoformat(),
            'deadline': effective_deadline.isoformat() if effective_deadline else None,
            'is_ontime': is_ontime,
        })

    rate = quantize_score((Decimal(ontime_count) / Decimal(total_completed)) * Decimal('100.00'))
    return {
        'has_data': True,
        'rate': rate,
        'completed_count': total_completed,
        'ontime_count': ontime_count,
        'late_count': late_count,
        'evidence_tasks': evidence_tasks[:25],
    }


def calculate_raw_score(
    actual_val: Decimal | float | None,
    target_val: Decimal | float,
    measurement_type: str = KPIDefinition.MeasurementType.PERCENTAGE,
    direction: str = KPIDefinition.Direction.HIGHER_IS_BETTER,
    min_val: Decimal | float = Decimal('0.00'),
    max_val: Decimal | float = Decimal('100.00'),
    no_data_policy: str = KPIDefinition.NoDataPolicy.EXCLUDED,
    has_data: bool = True,
) -> Decimal | None:
    """
    Computes mathematical raw score (0-100) based on direction, bounds, and no-data policies.
    """
    if not has_data or actual_val is None:
        if no_data_policy == KPIDefinition.NoDataPolicy.EXCLUDED:
            return None
        return Decimal('0.00')

    actual_dec = Decimal(str(actual_val))
    target_dec = Decimal(str(target_val))

    # 1. Boolean (Yes / No)
    if measurement_type == KPIDefinition.MeasurementType.BOOLEAN:
        return Decimal('100.00') if actual_dec > 0 else Decimal('0.00')

    # 2. Rating (1-5 scale)
    if measurement_type == KPIDefinition.MeasurementType.RATING:
        raw = (actual_dec / Decimal('5.00')) * Decimal('100.00')
        return quantize_score(min(Decimal('100.00'), max(Decimal('0.00'), raw)))

    # 3. Directional Scoring
    if direction == KPIDefinition.Direction.HIGHER_IS_BETTER:
        if target_dec > 0:
            raw = (actual_dec / target_dec) * Decimal('100.00')
        else:
            raw = Decimal('100.00') if actual_dec >= 0 else Decimal('0.00')
        return quantize_score(min(Decimal('100.00'), max(Decimal('0.00'), raw)))

    elif direction == KPIDefinition.Direction.LOWER_IS_BETTER:
        # If actual <= target, achieved 100%. If actual > target, degrade score.
        if actual_dec <= target_dec:
            return Decimal('100.00')
        if target_dec > 0:
            overshoot = actual_dec - target_dec
            penalty = (overshoot / target_dec) * Decimal('100.00')
            raw = max(Decimal('0.00'), Decimal('100.00') - penalty)
        else:
            raw = Decimal('0.00')
        return quantize_score(raw)

    elif direction == KPIDefinition.Direction.TARGET_IS_BEST:
        # Distance from target reduces score symmetrically
        deviation = abs(actual_dec - target_dec)
        if target_dec > 0:
            penalty = (deviation / target_dec) * Decimal('100.00')
            raw = max(Decimal('0.00'), Decimal('100.00') - penalty)
        else:
            raw = Decimal('100.00') if deviation == 0 else Decimal('0.00')
        return quantize_score(raw)

    # Fallback standard calculation
    if target_dec > 0:
        raw = (actual_dec / target_dec) * Decimal('100.00')
    else:
        raw = Decimal('100.00')
    return quantize_score(min(Decimal('100.00'), max(Decimal('0.00'), raw)))


def calculate_kpi_raw_score(
    kpi: KPIDefinition,
    actual_val: Decimal | float | None,
    target_val: Decimal | float | None = None,
) -> Decimal:
    """Helper wrapper for evaluating raw score directly against a KPIDefinition."""
    target = target_val if target_val is not None else kpi.target_value
    score = calculate_raw_score(
        actual_val=actual_val,
        target_val=target,
        measurement_type=kpi.measurement_type,
        direction=kpi.direction,
        min_val=kpi.min_value,
        max_val=kpi.max_value,
        no_data_policy=kpi.no_data_policy,
        has_data=True,
    )
    return score if score is not None else Decimal('0.00')


def normalize_assignment_weights(user: User, period: KPIPeriod) -> list[KPIAssignment]:
    """Helper wrapper for running normalization and returning active assignments."""
    normalize_period_weights(user, period)
    return list(KPIAssignment.objects.filter(user=user, period=period, is_active=True))


def normalize_period_weights(user: User, period: KPIPeriod) -> None:
    """
    Normalizes configured weights of active KPI assignments for an employee so they sum to exactly 100.00%.
    Stores both configured_weight and normalized_weight.
    """
    assignments = list(
        KPIAssignment.objects.filter(user=user, period=period, is_active=True).select_for_update()
    )
    if not assignments:
        return

    total_configured = sum(a.configured_weight for a in assignments)
    if total_configured <= Decimal('0.00'):
        # Equal distribution if all zero
        count = Decimal(len(assignments))
        equal_weight = quantize_score(Decimal('100.00') / count)
        for a in assignments:
            a.normalized_weight = equal_weight
            a.weight = equal_weight
            a.save(update_fields=['normalized_weight', 'weight'])
        return

    normalized_weights = []
    for a in assignments:
        norm = quantize_score((a.configured_weight / total_configured) * Decimal('100.00'))
        a.normalized_weight = norm
        a.weight = norm
        normalized_weights.append((a, norm))

    # Adjust rounding discrepancy (e.g. 99.99 or 100.01) on the assignment with the highest weight
    current_sum = sum(norm for _, norm in normalized_weights)
    diff = Decimal('100.00') - current_sum
    if diff != Decimal('0.00') and normalized_weights:
        # Find assignment with highest configured weight
        highest_assignment, highest_norm = max(normalized_weights, key=lambda item: item[0].configured_weight)
        highest_assignment.normalized_weight = quantize_score(highest_norm + diff)
        highest_assignment.weight = highest_assignment.normalized_weight

    for a in assignments:
        a.save(update_fields=['normalized_weight', 'weight'])


@transaction.atomic
def recalculate_employee_period_kpis(user: User, period: KPIPeriod, actor: User = None) -> list[KPIResult]:
    """
    Evaluates both automated task indicators and manual indicators for an employee in a given period.
    Generates transparent mathematical evidence and weighted scores.
    """
    if period.is_immutable:
        raise PermissionDenied("Cannot modify or recalculate KPI for a closed or signed period.")

    normalize_period_weights(user, period)

    assignments = KPIAssignment.objects.filter(
        user=user, period=period, is_active=True
    ).select_related('kpi', 'kpi__category')

    results = []
    for assign in assignments:
        kpi = assign.kpi
        result, _ = KPIResult.objects.get_or_create(assignment=assign)

        if result.is_locked:
            results.append(result)
            continue

        actual_val = result.actual_value
        evidence: dict[str, Any] = {}
        has_data = True

        # Check if this KPI is automated via Task System
        is_task_completion = (
            kpi.measurement_type == KPIDefinition.MeasurementType.TASK_COMPLETION
            or (kpi.source_type == KPIDefinition.SourceType.TASK_SYSTEM and 'COMPLETION' in kpi.code.upper())
        )
        is_deadline_compliance = (
            kpi.measurement_type == KPIDefinition.MeasurementType.DEADLINE_COMPLIANCE
            or (kpi.source_type == KPIDefinition.SourceType.TASK_SYSTEM and 'DEADLINE' in kpi.code.upper())
        )

        if is_task_completion:
            metric = calculate_task_completion_metric(user, period.start_date, period.end_date)
            has_data = metric['has_data']
            actual_val = metric['rate'] if has_data else Decimal('0.00')
            evidence = {
                'source': 'TASK_SYSTEM',
                'metric_type': 'TASK_COMPLETION',
                'has_data': has_data,
                'eligible_tasks_count': metric['eligible_count'],
                'completed_tasks_count': metric['completed_count'],
                'completion_percentage': float(metric['rate']) if metric['rate'] is not None else None,
                'formula': f"({metric['completed_count']} completed / {metric['eligible_count']} eligible) * 100",
                'target': float(assign.target_value),
                'tasks_sample': metric['evidence_tasks'],
            }
        elif is_deadline_compliance:
            metric = calculate_deadline_compliance_metric(user, period.start_date, period.end_date)
            has_data = metric['has_data']
            actual_val = metric['rate'] if has_data else Decimal('0.00')
            evidence = {
                'source': 'TASK_SYSTEM',
                'metric_type': 'DEADLINE_COMPLIANCE',
                'has_data': has_data,
                'completed_tasks_count': metric['completed_count'],
                'ontime_tasks_count': metric['ontime_count'],
                'late_tasks_count': metric['late_count'],
                'compliance_percentage': float(metric['rate']) if metric['rate'] is not None else None,
                'formula': f"({metric['ontime_count']} on-time / {metric['completed_count']} completed) * 100",
                'target': float(assign.target_value),
                'tasks_sample': metric['evidence_tasks'],
            }
        else:
            # Manual / Subjective Evaluation
            evidence = {
                'source': assign.source_type or kpi.source_type,
                'metric_type': kpi.measurement_type,
                'has_data': True,
                'actual_value': float(actual_val),
                'target_value': float(assign.target_value),
                'evaluator': result.evaluated_by.display_name if result.evaluated_by else None,
                'notes': result.notes,
            }

        raw = calculate_raw_score(
            actual_val=actual_val,
            target_val=assign.target_value,
            measurement_type=kpi.measurement_type,
            direction=kpi.direction,
            min_val=kpi.min_value,
            max_val=kpi.max_value,
            no_data_policy=kpi.no_data_policy,
            has_data=has_data,
        )

        raw_score = raw if raw is not None else Decimal('0.00')
        weighted_score = quantize_score((raw_score * assign.normalized_weight) / Decimal('100.00'))

        evidence['raw_score'] = float(raw_score)
        evidence['configured_weight'] = float(assign.configured_weight)
        evidence['normalized_weight'] = float(assign.normalized_weight)
        evidence['weighted_score'] = float(weighted_score)
        evidence['calculated_at'] = timezone.now().isoformat()

        result.actual_value = actual_val if actual_val is not None else Decimal('0.00')
        result.raw_score = raw_score
        result.configured_weight = assign.configured_weight
        result.normalized_weight = assign.normalized_weight
        result.weighted_score = weighted_score
        result.calculation_evidence = evidence

        # Automated task results move to REVIEWED/SUBMITTED automatically
        if is_task_completion or is_deadline_compliance:
            if result.status == KPIResult.Status.DRAFT:
                result.status = KPIResult.Status.SUBMITTED
            if actor:
                result.evaluated_by = actor
            result.evaluated_at = timezone.now()

        result.save()
        results.append(result)

    return results
