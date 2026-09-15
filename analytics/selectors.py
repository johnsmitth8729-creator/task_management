from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Avg, Case, Count, F, Max, Min, Q, Sum, Value, When
from django.db.models.functions import Coalesce, TruncDate, TruncMonth, TruncWeek
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from core.models import AuditLog
from organization.models import Department, Position
from tasks.models import Task, TaskApproval, TaskAssignment, TaskSubmission

try:
    from hr.models import EmployeeGrade, EmploymentHistory
except ImportError:
    EmployeeGrade = None
    EmploymentHistory = None

try:
    from kpi.models import KPIPeriod, KPIResult
except ImportError:
    KPIPeriod = None
    KPIResult = None

try:
    from payroll.models import PayrollPeriod, PayrollRecord
except ImportError:
    PayrollPeriod = None
    PayrollRecord = None

try:
    from signatures.models import ElectronicSignature, SignatureVerificationEvent
except ImportError:
    ElectronicSignature = None
    SignatureVerificationEvent = None


# ===========================================================================
# DATE RANGE PARSING
# ===========================================================================

def parse_date_range(period: str | None = None, start_date_str: str | None = None, end_date_str: str | None = None) -> tuple[datetime, datetime, str]:
    """
    Parses date range filters into timezone-aware (start_datetime, end_datetime, label).
    Supported presets: 'today', 'yesterday', '7d', '30d', 'this_month', 'last_month', 'this_quarter', 'this_year', 'custom'.
    """
    now = timezone.now()
    today = now.date()

    if period == 'today':
        start = timezone.make_aware(datetime.combine(today, time.min))
        end = timezone.make_aware(datetime.combine(today, time.max))
        label = _('Today')
    elif period == 'yesterday':
        yesterday = today - timedelta(days=1)
        start = timezone.make_aware(datetime.combine(yesterday, time.min))
        end = timezone.make_aware(datetime.combine(yesterday, time.max))
        label = _('Yesterday')
    elif period == '7d':
        start = now - timedelta(days=7)
        end = now
        label = _('Last 7 Days')
    elif period == '30d' or not period:
        start = now - timedelta(days=30)
        end = now
        label = _('Last 30 Days')
    elif period == 'this_month':
        first_day = today.replace(day=1)
        start = timezone.make_aware(datetime.combine(first_day, time.min))
        end = now
        label = _('This Month')
    elif period == 'last_month':
        first_this_month = today.replace(day=1)
        last_day_prev = first_this_month - timedelta(days=1)
        first_day_prev = last_day_prev.replace(day=1)
        start = timezone.make_aware(datetime.combine(first_day_prev, time.min))
        end = timezone.make_aware(datetime.combine(last_day_prev, time.max))
        label = _('Last Month')
    elif period == 'this_quarter':
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        first_day_quarter = today.replace(month=quarter_month, day=1)
        start = timezone.make_aware(datetime.combine(first_day_quarter, time.min))
        end = now
        label = _('This Quarter')
    elif period == 'this_year':
        first_day_year = today.replace(month=1, day=1)
        start = timezone.make_aware(datetime.combine(first_day_year, time.min))
        end = now
        label = _('This Year')
    elif period == 'custom':
        if not start_date_str or not end_date_str:
            # Fallback to 30d
            start = now - timedelta(days=30)
            end = now
            label = _('Last 30 Days')
        else:
            try:
                s_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                e_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if s_date > e_date:
                    raise ValidationError(_('Start date cannot be after end date.'))
                start = timezone.make_aware(datetime.combine(s_date, time.min))
                end = timezone.make_aware(datetime.combine(e_date, time.max))
                label = f"{s_date} — {e_date}"
            except (ValueError, ValidationError):
                start = now - timedelta(days=30)
                end = now
                label = _('Last 30 Days')
    else:
        start = now - timedelta(days=30)
        end = now
        label = _('Last 30 Days')

    return start, end, label


# ===========================================================================
# SCOPED QUERYSETS
# ===========================================================================

def get_scoped_departments_for_user(user: User):
    """Returns the Department queryset visible to the user based on RBAC."""
    if not user or not user.is_authenticated:
        return Department.objects.none()
    if user.is_superuser or user.is_rector or user.is_hr:
        return Department.objects.filter(is_active=True).order_by('name')
    if user.is_vice_rector:
        dept_ids = user.department_responsibilities.filter(is_active=True).values_list('department_id', flat=True)
        return Department.objects.filter(id__in=dept_ids, is_active=True).order_by('name')
    if user.is_department_head and user.department:
        return Department.objects.filter(id=user.department_id, is_active=True)
    return Department.objects.none()


def get_scoped_tasks(user: User, department_id: str | None = None, date_range: tuple[datetime, datetime] | None = None, status: str | None = None):
    """
    Returns a Task queryset strictly scoped to user permissions, optional department filter, and date range.
    """
    if not user or not user.is_authenticated:
        return Task.objects.none()

    qs = Task.objects.filter(archived_at__isnull=True)

    # Department and role scoping
    if user.is_superuser or user.is_rector:
        if department_id:
            qs = qs.filter(responsible_department_id=department_id)
    elif user.is_vice_rector:
        responsible_dept_ids = list(user.department_responsibilities.filter(is_active=True).values_list('department_id', flat=True))
        if department_id:
            if department_id in [str(d) for d in responsible_dept_ids]:
                qs = qs.filter(responsible_department_id=department_id)
            else:
                return Task.objects.none()
        else:
            qs = qs.filter(responsible_department_id__in=responsible_dept_ids)
    elif user.is_department_head:
        if not user.department_id:
            return Task.objects.none()
        if department_id and str(department_id) != str(user.department_id):
            return Task.objects.none()
        qs = qs.filter(responsible_department_id=user.department_id)
    else:
        # Regular employee: own assigned tasks
        qs = qs.filter(assignments__user=user).distinct()

    # Date range filtering (by created_at or completion)
    if date_range:
        start, end = date_range
        qs = qs.filter(created_at__gte=start, created_at__lte=end)

    # Status filter
    if status and status != 'ALL':
        qs = qs.filter(status=status)

    return qs


# ===========================================================================
# EXECUTIVE & MACRO METRICS
# ===========================================================================

def get_executive_metrics(user: User, department_id: str | None = None, date_range: tuple[datetime, datetime] | None = None) -> dict:
    """
    Computes aggregated executive metrics for Rector, Vice Rector, or Department Head.
    """
    tasks_qs = get_scoped_tasks(user, department_id=department_id, date_range=date_range)
    total_tasks = tasks_qs.count()

    now = timezone.now()
    today_date = now.date()

    # Aggregations in single DB query
    agg = tasks_qs.aggregate(
        completed_count=Count('id', filter=Q(status=Task.Status.COMPLETED)),
        cancelled_count=Count('id', filter=Q(status=Task.Status.CANCELLED)),
        assigned_count=Count('id', filter=Q(status=Task.Status.ASSIGNED)),
        in_progress_count=Count('id', filter=Q(status=Task.Status.IN_PROGRESS)),
        overdue_count=Count(
            'id',
            filter=~Q(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]) & Q(deadline__lt=today_date)
        ),
        ontime_completed_count=Count(
            'id',
            filter=Q(status=Task.Status.COMPLETED) & (Q(completed_at__date__lte=F('deadline')) | Q(deadline__isnull=True))
        ),
    )

    completed = agg['completed_count'] or 0
    cancelled = agg['cancelled_count'] or 0
    overdue = agg['overdue_count'] or 0
    ontime_completed = agg['ontime_completed_count'] or 0

    # Submission & approval queues
    pending_first_approval = TaskSubmission.objects.filter(
        task__in=tasks_qs, status=TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL
    ).values('task_id').distinct().count()

    pending_final_approval = TaskSubmission.objects.filter(
        task__in=tasks_qs, status=TaskSubmission.SubmissionStatus.FIRST_APPROVED
    ).values('task_id').distinct().count()

    rejected = TaskApproval.objects.filter(
        task__in=tasks_qs, decision=TaskApproval.Decision.REJECTED
    ).values('task_id').distinct().count()

    active_tasks = (
        (agg['assigned_count'] or 0) +
        (agg['in_progress_count'] or 0)
    )

    # Electronic signature metrics
    signed_tasks = 0
    pending_signature = 0
    if ElectronicSignature:
        # Tasks completed with signature
        signed_task_ids = set(
            ElectronicSignature.objects.filter(status='SIGNED')
            .values_list('task_id', flat=True)
        )
        completed_tasks_qs = tasks_qs.filter(status=Task.Status.COMPLETED)
        signed_tasks = completed_tasks_qs.filter(id__in=signed_task_ids).count()
        pending_signature = completed_tasks_qs.exclude(id__in=signed_task_ids).count()

    # Rates calculation (Safe division)
    eligible_for_completion = completed + active_tasks + overdue
    completion_rate = round((completed / eligible_for_completion * 100), 1) if eligible_for_completion > 0 else Decimal('0.0')
    ontime_rate = round((ontime_completed / completed * 100), 1) if completed > 0 else Decimal('0.0')
    rejection_rate = round((rejected / eligible_for_completion * 100), 1) if eligible_for_completion > 0 else Decimal('0.0')
    overdue_rate = round((overdue / eligible_for_completion * 100), 1) if eligible_for_completion > 0 else Decimal('0.0')

    # Average completion time (in days)
    avg_days = 0.0
    completed_with_dates = tasks_qs.filter(status=Task.Status.COMPLETED, completed_at__isnull=False)
    if completed_with_dates.exists():
        total_duration_sec = sum(
            (t.completed_at - t.created_at).total_seconds()
            for t in completed_with_dates[:200]  # Limit to 200 for fast memory calc
        )
        if completed_with_dates.count() > 0:
            avg_days = round(total_duration_sec / (completed_with_dates.count() * 86400), 1)

    # Headcount metrics
    dept_qs = get_scoped_departments_for_user(user)
    if department_id:
        dept_qs = dept_qs.filter(id=department_id)
    
    user_qs = User.objects.filter(department__in=dept_qs)
    total_employees = user_qs.count()
    active_employees = user_qs.filter(is_active=True).count()

    # KPI Average
    kpi_avg = Decimal('0.0')
    if KPIResult:
        kpi_qs = KPIResult.objects.filter(assignment__user__in=user_qs)
        if date_range:
            kpi_qs = kpi_qs.filter(created_at__gte=date_range[0], created_at__lte=date_range[1])
        avg_res = kpi_qs.aggregate(avg_score=Avg('raw_score'))['avg_score']
        if avg_res is not None:
            kpi_avg = round(Decimal(str(avg_res)), 1)

    return {
        'total_tasks': total_tasks,
        'active_tasks': active_tasks,
        'completed_tasks': completed,
        'overdue_tasks': overdue,
        'rejected_tasks': rejected,
        'cancelled_tasks': cancelled,
        'pending_first_approval': pending_first_approval,
        'pending_final_approval': pending_final_approval,
        'signed_tasks': signed_tasks,
        'pending_signature': pending_signature,
        'completion_rate': float(completion_rate),
        'ontime_rate': float(ontime_rate),
        'rejection_rate': float(rejection_rate),
        'overdue_rate': float(overdue_rate),
        'avg_completion_days': avg_days,
        'total_employees': total_employees,
        'active_employees': active_employees,
        'kpi_avg_score': float(kpi_avg),
    }


# ===========================================================================
# DEPARTMENT COMPARISON SELECTOR
# ===========================================================================

def get_department_comparison_data(user: User, date_range: tuple[datetime, datetime] | None = None) -> list[dict]:
    """
    Returns comparative task and performance metrics across all departments visible to the user.
    Strictly omits all individual salary/compensation fields.
    """
    dept_qs = get_scoped_departments_for_user(user)
    now = timezone.now()
    results = []

    today_date = timezone.now().date()
    for dept in dept_qs:
        dept_tasks = Task.objects.filter(responsible_department=dept, archived_at__isnull=True)
        if date_range:
            dept_tasks = dept_tasks.filter(created_at__gte=date_range[0], created_at__lte=date_range[1])

        total = dept_tasks.count()
        agg = dept_tasks.aggregate(
            completed=Count('id', filter=Q(status=Task.Status.COMPLETED)),
            overdue=Count(
                'id',
                filter=~Q(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]) & Q(deadline__lt=today_date)
            ),
            ontime=Count(
                'id',
                filter=Q(status=Task.Status.COMPLETED) & (Q(completed_at__date__lte=F('deadline')) | Q(deadline__isnull=True))
            ),
            active=Count(
                'id',
                filter=Q(status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS])
            ),
        )

        completed = agg['completed'] or 0
        active = agg['active'] or 0
        overdue = agg['overdue'] or 0
        rejected = TaskApproval.objects.filter(
            task__in=dept_tasks, decision=TaskApproval.Decision.REJECTED
        ).values('task_id').distinct().count()
        ontime = agg['ontime'] or 0

        eligible = completed + active + overdue
        comp_rate = round((completed / eligible * 100), 1) if eligible > 0 else 0.0
        ontime_rate = round((ontime / completed * 100), 1) if completed > 0 else 0.0

        # Avg completion time in days
        avg_days = 0.0
        completed_tasks = dept_tasks.filter(status=Task.Status.COMPLETED, completed_at__isnull=False)
        if completed_tasks.exists():
            durations = [(t.completed_at - t.created_at).total_seconds() for t in completed_tasks[:100]]
            avg_days = round(sum(durations) / (len(durations) * 86400), 1)

        # Department KPI Average
        kpi_score = 0.0
        if KPIResult:
            kpi_qs = KPIResult.objects.filter(assignment__user__department=dept)
            if date_range:
                kpi_qs = kpi_qs.filter(created_at__gte=date_range[0], created_at__lte=date_range[1])
            avg_kpi = kpi_qs.aggregate(avg=Avg('raw_score'))['avg']
            if avg_kpi is not None:
                kpi_score = round(float(avg_kpi), 1)

        employee_count = dept.users.filter(is_active=True).count()

        results.append({
            'department_id': str(dept.id),
            'department_name': dept.name,
            'department_code': dept.code,
            'employee_count': employee_count,
            'total_tasks': total,
            'completed': completed,
            'active': active,
            'overdue': overdue,
            'rejected': rejected,
            'completion_rate': comp_rate,
            'ontime_rate': ontime_rate,
            'avg_completion_days': avg_days,
            'kpi_score': kpi_score,
        })

    # Sort by completion rate descending
    results.sort(key=lambda x: x['completion_rate'], reverse=True)
    return results


# ===========================================================================
# WORKFLOW BOTTLENECK METRICS
# ===========================================================================

def get_bottleneck_metrics(user: User, department_id: str | None = None, date_range: tuple[datetime, datetime] | None = None) -> dict:
    """
    Computes queue bottlenecks and average wait times in each workflow step:
    1. Assigned -> Submitted (Employee execution)
    2. Submitted -> First Approval (Dept Head queue)
    3. First Approval -> Final Approval (Management queue)
    4. Final Approval -> Electronic Signature (Signing queue)
    """
    tasks_qs = get_scoped_tasks(user, department_id=department_id, date_range=date_range)
    
    # Counts waiting in queues
    waiting_employee = TaskAssignment.objects.filter(
        task__in=tasks_qs,
        assignment_status__in=[TaskAssignment.AssignmentStatus.ASSIGNED, TaskAssignment.AssignmentStatus.IN_PROGRESS]
    ).count()
    waiting_first_approval = TaskAssignment.objects.filter(
        task__in=tasks_qs,
        assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED
    ).count()
    waiting_final_approval = TaskAssignment.objects.filter(
        task__in=tasks_qs,
        assignment_status=TaskAssignment.AssignmentStatus.SECOND_APPROVAL
    ).count()

    signed_ids = set()
    if ElectronicSignature:
        signed_ids = set(ElectronicSignature.objects.filter(status='SIGNED').values_list('task_id', flat=True))
    
    waiting_signature = tasks_qs.filter(status=Task.Status.COMPLETED).exclude(id__in=signed_ids).count()

    # Average wait durations calculation from submissions and approval steps
    avg_submission_days = 0.0
    avg_first_approval_days = 0.0
    avg_final_approval_days = 0.0
    avg_signature_days = 0.0

    submissions = TaskSubmission.objects.filter(task__in=tasks_qs).select_related('task')[:150]
    if submissions.exists():
        durations = []
        for s in submissions:
            if s.created_at and s.task.created_at:
                durations.append((s.created_at - s.task.created_at).total_seconds())
        if durations:
            avg_submission_days = round(sum(durations) / (len(durations) * 86400), 1)

    approvals = TaskApproval.objects.filter(task__in=tasks_qs, decision='APPROVED').select_related('submission', 'task')
    first_apps = approvals.filter(stage=TaskApproval.Stage.FIRST_APPROVAL)[:150]
    if first_apps.exists():
        durs = [
            (fa.created_at - fa.submission.submitted_at).total_seconds()
            for fa in first_apps if fa.submission and fa.submission.submitted_at and fa.created_at
        ]
        if durs:
            avg_first_approval_days = round(sum(durs) / (len(durs) * 86400), 1)

    final_apps = approvals.filter(stage__in=[TaskApproval.Stage.SECOND_APPROVAL, TaskApproval.Stage.FINAL_APPROVAL])[:150]
    if final_apps.exists():
        durs = [
            (fa.created_at - fa.submission.submitted_at).total_seconds()
            for fa in final_apps if fa.submission and fa.submission.submitted_at and fa.created_at
        ]
        if durs:
            avg_final_approval_days = round(sum(durs) / (len(durs) * 86400), 1)

    if ElectronicSignature:
        sigs = ElectronicSignature.objects.filter(task__in=tasks_qs, status='SIGNED').select_related('task')[:150]
        if sigs.exists():
            durs = []
            for sig in sigs:
                if sig.task.completed_at and sig.signed_at:
                    durs.append((sig.signed_at - sig.task.completed_at).total_seconds())
            if durs:
                avg_signature_days = round(sum(durs) / (len(durs) * 86400), 1)

    return {
        'waiting_employee': waiting_employee,
        'waiting_first_approval': waiting_first_approval,
        'waiting_final_approval': waiting_final_approval,
        'waiting_signature': waiting_signature,
        'avg_submission_days': avg_submission_days,
        'avg_first_approval_days': avg_first_approval_days,
        'avg_final_approval_days': avg_final_approval_days,
        'avg_signature_days': avg_signature_days,
    }


# ===========================================================================
# DEADLINE ANALYTICS SELECTOR
# ===========================================================================

def get_deadline_metrics(user, department_id=None, date_range=None) -> dict:
    """
    Computes strict deadline compliance metrics, overdue volumes, and distributions.
    """
    tasks_qs = get_scoped_tasks(user, department_id=department_id, date_range=date_range)
    now = timezone.now()
    today_date = now.date()
    tomorrow_date = today_date + timedelta(days=1)
    week_date = today_date + timedelta(days=7)

    due_today = tasks_qs.filter(
        deadline=today_date,
        status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]
    ).count()

    due_tomorrow = tasks_qs.filter(
        deadline=tomorrow_date,
        status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]
    ).count()

    due_this_week = tasks_qs.filter(
        deadline__gte=today_date, deadline__lte=week_date,
        status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]
    ).count()

    overdue = tasks_qs.filter(
        deadline__lt=today_date,
        status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]
    ).count()

    completed_qs = tasks_qs.filter(status=Task.Status.COMPLETED)
    total_completed = completed_qs.count()

    completed_before_deadline = completed_qs.filter(completed_at__date__lt=F('deadline')).count()
    completed_on_deadline = completed_qs.filter(completed_at__date=F('deadline')).count()
    completed_after_deadline = completed_qs.filter(completed_at__date__gt=F('deadline')).count()

    compliance_rate = 0.0
    if total_completed > 0:
        compliance_rate = round(((completed_before_deadline + completed_on_deadline) / total_completed * 100), 1)

    return {
        'due_today': due_today,
        'due_tomorrow': due_tomorrow,
        'due_this_week': due_this_week,
        'overdue': overdue,
        'completed_before_deadline': completed_before_deadline,
        'completed_on_deadline': completed_on_deadline,
        'completed_after_deadline': completed_after_deadline,
        'deadline_compliance_rate': compliance_rate,
    }


# ===========================================================================
# ELECTRONIC SIGNATURE ANALYTICS
# ===========================================================================

def get_signature_metrics(user: User, date_range: tuple[datetime, datetime] | None = None) -> dict:
    """
    Computes Phase 9 cryptographic signature throughput and verification integrity stats.
    Strictly avoids exposing private keys or confidential signature payloads.
    """
    if not ElectronicSignature:
        return {}

    now = timezone.now()
    today_start = timezone.make_aware(datetime.combine(now.date(), time.min))
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    scoped_tasks = get_scoped_tasks(user, date_range=date_range)
    sigs = ElectronicSignature.objects.filter(task__in=scoped_tasks)

    if date_range:
        sigs = sigs.filter(signed_at__gte=date_range[0], signed_at__lte=date_range[1])

    total_signed = sigs.filter(status='SIGNED').count()
    signed_today = sigs.filter(status='SIGNED', signed_at__gte=today_start).count()
    signed_this_week = sigs.filter(status='SIGNED', signed_at__gte=week_start).count()
    signed_this_month = sigs.filter(status='SIGNED', signed_at__gte=month_start).count()
    revoked_count = sigs.filter(status='REVOKED').count()

    # Pending signature
    completed_count = scoped_tasks.filter(status=Task.Status.COMPLETED).count()
    pending_signature = max(0, completed_count - total_signed)
    signature_rate = round((total_signed / completed_count * 100), 1) if completed_count > 0 else 0.0

    # Verification events
    total_verifications = 0
    invalid_verifications = 0
    if SignatureVerificationEvent:
        events = SignatureVerificationEvent.objects.filter(signature__in=sigs)
        total_verifications = events.count()
        invalid_verifications = events.filter(is_valid=False).count()

    # Signatures by signer role
    rector_signs = sigs.filter(signer__roles__code='RECTOR', status='SIGNED').count()
    vice_rector_signs = sigs.filter(signer__roles__code='VICE_RECTOR', status='SIGNED').count()
    superadmin_signs = sigs.filter(signer__is_superuser=True, status='SIGNED').count()

    return {
        'total_signed': total_signed,
        'signed_today': signed_today,
        'signed_this_week': signed_this_week,
        'signed_this_month': signed_this_month,
        'revoked_count': revoked_count,
        'pending_signature': pending_signature,
        'signature_rate': signature_rate,
        'total_verifications': total_verifications,
        'invalid_verifications': invalid_verifications,
        'by_signer': {
            'Rector': rector_signs,
            'Vice Rector': vice_rector_signs,
            'Superadmin': superadmin_signs,
        }
    }


# ===========================================================================
# HR ORGANIZATIONAL ANALYTICS
# ===========================================================================

def get_hr_analytics_metrics(user: User, date_range: tuple[datetime, datetime] | None = None) -> dict:
    """
    Computes workforce distribution and staffing metrics for HR Managers and Rector.
    """
    users = User.objects.all()
    total = users.count()
    active = users.filter(is_active=True).count()
    inactive = users.filter(is_active=False).count()
    
    # Status breakdown
    on_leave = 0
    terminated = 0
    if hasattr(User, 'employment_status'):
        on_leave = users.filter(employment_status='ON_LEAVE').count()
        terminated = users.filter(employment_status='TERMINATED').count()

    # Position & Department distribution
    dept_dist = list(
        Department.objects.filter(is_active=True)
        .annotate(headcount=Count('users', filter=Q(users__is_active=True)))
        .values('name', 'headcount')
        .order_by('-headcount')[:8]
    )

    # Performance summary for HR
    kpi_avg = 0.0
    if KPIResult:
        avg = KPIResult.objects.aggregate(a=Avg('raw_score'))['a']
        if avg is not None:
            kpi_avg = round(float(avg), 1)

    return {
        'total_employees': total,
        'active_employees': active,
        'inactive_employees': inactive,
        'on_leave_employees': on_leave,
        'terminated_employees': terminated,
        'department_distribution': dept_dist,
        'average_kpi_score': kpi_avg,
    }


# ===========================================================================
# PAYROLL ANALYTICS (MACRO & AGGREGATE ONLY)
# ===========================================================================

def get_payroll_analytics_metrics(user: User, department_id: str | None = None, date_range: tuple[datetime, datetime] | None = None) -> dict:
    """
    Computes macro payroll totals for Finance and Superadmin.
    Strictly aggregates data without returning individual employee compensation.
    """
    if not PayrollRecord:
        return {}

    qs = PayrollRecord.objects.all()
    if department_id:
        qs = qs.filter(employee__department_id=department_id)
    if date_range:
        qs = qs.filter(period__start_date__gte=date_range[0].date(), period__end_date__lte=date_range[1].date())

    agg = qs.aggregate(
        total_gross=Coalesce(Sum('gross_salary'), Decimal('0.00')),
        total_net=Coalesce(Sum('net_salary'), Decimal('0.00')),
        total_bonuses=Coalesce(Sum('total_bonuses'), Decimal('0.00')),
        total_kpi=Coalesce(Sum('kpi_bonus'), Decimal('0.00')),
        total_deductions=Coalesce(Sum('total_deductions'), Decimal('0.00')),
        total_tax=Coalesce(Sum('tax_total'), Decimal('0.00')),
        avg_gross=Coalesce(Avg('gross_salary'), Decimal('0.00')),
        record_count=Count('id'),
    )

    # Department spend breakdown
    dept_spend = []
    if Department:
        spend_rows = (
            Department.objects.filter(is_active=True)
            .annotate(dept_total=Coalesce(Sum('users__payroll_records__gross_salary'), Decimal('0.00')))
            .filter(dept_total__gt=0)
            .values('name', 'dept_total')
            .order_by('-dept_total')[:6]
        )
        for r in spend_rows:
            dept_spend.append({
                'name': r['name'],
                'total': float(r['dept_total'])
            })

    return {
        'total_gross': float(agg['total_gross']),
        'total_net': float(agg['total_net']),
        'total_bonuses': float(agg['total_bonuses']),
        'total_kpi': float(agg['total_kpi']),
        'total_deductions': float(agg['total_deductions']),
        'total_tax': float(agg['total_tax']),
        'avg_gross': float(agg['avg_gross']),
        'record_count': agg['record_count'],
        'department_spend': dept_spend,
    }


# ===========================================================================
# AUDIT & SECURITY ANALYTICS (SUPERADMIN ONLY)
# ===========================================================================

def get_audit_security_metrics(user: User, date_range: tuple[datetime, datetime] | None = None) -> dict:
    """
    Computes system audit frequencies, security events, and administrative activities for Superadmin.
    """
    qs = AuditLog.objects.all()
    if date_range:
        qs = qs.filter(created_at__gte=date_range[0], created_at__lte=date_range[1])

    total_events = qs.count()

    # Action distribution
    top_actions = list(
        qs.values('action')
        .annotate(count=Count('id'))
        .order_by('-count')[:8]
    )

    # Security failure indicators
    sig_failures = qs.filter(action='SIGNATURE_VERIFICATION_FAILED').count()
    role_changes = qs.filter(action__in=['ROLE_CHANGED', 'ROLE_ASSIGNED', 'ROLE_REMOVED']).count()
    deletions = qs.filter(action__icontains='DELETED').count()

    return {
        'total_audit_events': total_events,
        'top_actions': top_actions,
        'signature_verification_failures': sig_failures,
        'role_security_changes': role_changes,
        'critical_deletions': deletions,
    }


# ===========================================================================
# EMPLOYEE PERSONAL ANALYTICS
# ===========================================================================

def get_employee_personal_metrics(employee: User, date_range: tuple[datetime, datetime] | None = None) -> dict:
    """
    Computes personal workload, turnaround time, and KPI trajectory for an employee.
    """
    assignments = TaskAssignment.objects.filter(user=employee).select_related('task')
    if date_range:
        assignments = assignments.filter(created_at__gte=date_range[0], created_at__lte=date_range[1])

    total = assignments.count()
    now = timezone.now()
    today_date = now.date()

    completed = assignments.filter(assignment_status=TaskAssignment.AssignmentStatus.APPROVED).count()
    in_progress = assignments.filter(assignment_status=TaskAssignment.AssignmentStatus.IN_PROGRESS).count()
    submitted = assignments.filter(assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED).count()
    overdue = assignments.filter(
        ~Q(assignment_status=TaskAssignment.AssignmentStatus.APPROVED) & Q(task__deadline__lt=today_date)
    ).count()

    ontime_count = assignments.filter(
        assignment_status=TaskAssignment.AssignmentStatus.APPROVED,
        task__completed_at__date__lte=F('task__deadline')
    ).count()

    ontime_rate = round((ontime_count / completed * 100), 1) if completed > 0 else 0.0

    # Turnaround time
    avg_days = 0.0
    completed_ass = assignments.filter(assignment_status=TaskAssignment.AssignmentStatus.APPROVED, task__completed_at__isnull=False)
    if completed_ass.exists():
        durs = [(a.task.completed_at - a.created_at).total_seconds() for a in completed_ass[:100] if a.task.completed_at and a.created_at]
        if durs:
            avg_days = round(sum(durs) / (len(durs) * 86400), 1)

    # Personal KPI score
    my_kpi = 0.0
    if KPIResult:
        rec = KPIResult.objects.filter(assignment__user=employee).order_by('-created_at').first()
        if rec and rec.raw_score is not None:
            my_kpi = round(float(rec.raw_score), 1)

    # Signed tasks where employee was assignee
    signed_tasks_count = 0
    if ElectronicSignature:
        task_ids = assignments.filter(assignment_status=TaskAssignment.AssignmentStatus.APPROVED).values_list('task_id', flat=True)
        signed_tasks_count = ElectronicSignature.objects.filter(task_id__in=task_ids, status='SIGNED').count()

    return {
        'total_assigned': total,
        'completed': completed,
        'in_progress': in_progress,
        'submitted': submitted,
        'overdue': overdue,
        'ontime_rate': ontime_rate,
        'avg_turnaround_days': avg_days,
        'my_kpi_score': my_kpi,
        'signed_tasks_count': signed_tasks_count,
    }
