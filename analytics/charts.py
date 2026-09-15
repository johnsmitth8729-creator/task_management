from datetime import timedelta
from django.db.models import Count, Q
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone
from django.utils.translation import gettext as _

from analytics.selectors import (
    get_deadline_metrics,
    get_department_comparison_data,
    get_scoped_tasks,
    get_signature_metrics,
)
from tasks.models import Task

try:
    from signatures.models import ElectronicSignature
except ImportError:
    ElectronicSignature = None


def get_task_status_chart_data(user, department_id=None, date_range=None) -> dict:
    """
    Returns data formatted for a Doughnut chart showing task status breakdown.
    """
    tasks_qs = get_scoped_tasks(user, department_id=department_id, date_range=date_range)
    agg = tasks_qs.aggregate(
        completed=Count('id', filter=Q(status=Task.Status.COMPLETED)),
        in_progress=Count('id', filter=Q(status=Task.Status.IN_PROGRESS)),
        assigned=Count('id', filter=Q(status=Task.Status.ASSIGNED)),
        cancelled=Count('id', filter=Q(status=Task.Status.CANCELLED)),
        draft=Count('id', filter=Q(status__in=[Task.Status.DRAFT, Task.Status.CREATED])),
    )

    labels = [
        _('Completed'),
        _('In Progress'),
        _('Assigned'),
        _('Cancelled'),
        _('Draft / Created'),
    ]
    data = [
        agg['completed'] or 0,
        agg['in_progress'] or 0,
        agg['assigned'] or 0,
        agg['cancelled'] or 0,
        agg['draft'] or 0,
    ]
    colors = ['#10b981', '#3b82f6', '#8b5cf6', '#ef4444', '#64748b']

    return {
        'labels': labels,
        'datasets': [{
            'data': data,
            'backgroundColor': colors,
            'borderWidth': 1,
        }]
    }


def get_task_trends_chart_data(user, department_id=None, date_range=None) -> dict:
    """
    Returns time-series data for task creation vs completion over time.
    Automatically groups by Day, Week, or Month based on date span.
    """
    tasks_qs = get_scoped_tasks(user, department_id=department_id, date_range=date_range)
    if not date_range:
        now = timezone.now()
        start = now - timedelta(days=30)
        end = now
    else:
        start, end = date_range

    delta_days = (end - start).days

    if delta_days <= 14:
        trunc_fn = TruncDate
        date_format = '%d %b'
    elif delta_days <= 90:
        trunc_fn = TruncWeek
        date_format = 'Wk %W (%d %b)'
    else:
        trunc_fn = TruncMonth
        date_format = '%b %Y'

    created_series = (
        tasks_qs.annotate(period=trunc_fn('created_at'))
        .values('period')
        .annotate(count=Count('id'))
        .order_by('period')
    )

    completed_series = (
        tasks_qs.filter(status=Task.Status.COMPLETED, completed_at__isnull=False)
        .annotate(period=trunc_fn('completed_at'))
        .values('period')
        .annotate(count=Count('id'))
        .order_by('period')
    )

    # Combine periods
    periods_map = {}
    for item in created_series:
        p = item['period']
        if p:
            lbl = p.strftime(date_format)
            if lbl not in periods_map:
                periods_map[lbl] = {'created': 0, 'completed': 0}
            periods_map[lbl]['created'] = item['count']

    for item in completed_series:
        p = item['period']
        if p:
            lbl = p.strftime(date_format)
            if lbl not in periods_map:
                periods_map[lbl] = {'created': 0, 'completed': 0}
            periods_map[lbl]['completed'] = item['count']

    labels = list(periods_map.keys())
    created_data = [periods_map[l]['created'] for l in labels]
    completed_data = [periods_map[l]['completed'] for l in labels]

    return {
        'labels': labels,
        'datasets': [
            {
                'label': _('Tasks Created'),
                'data': created_data,
                'borderColor': '#3b82f6',
                'backgroundColor': 'rgba(59, 130, 246, 0.1)',
                'tension': 0.3,
                'fill': True,
            },
            {
                'label': _('Tasks Completed'),
                'data': completed_data,
                'borderColor': '#10b981',
                'backgroundColor': 'rgba(16, 185, 129, 0.1)',
                'tension': 0.3,
                'fill': True,
            }
        ]
    }


def get_department_comparison_chart_data(user, date_range=None) -> dict:
    """
    Returns Bar chart data comparing completion rates across departments.
    """
    dept_data = get_department_comparison_data(user, date_range=date_range)
    labels = [d['department_name'] for d in dept_data[:8]]
    completion_rates = [d['completion_rate'] for d in dept_data[:8]]
    ontime_rates = [d['ontime_rate'] for d in dept_data[:8]]

    return {
        'labels': labels,
        'datasets': [
            {
                'label': _('Completion Rate (%)'),
                'data': completion_rates,
                'backgroundColor': '#3b82f6',
            },
            {
                'label': _('On-Time Rate (%)'),
                'data': ontime_rates,
                'backgroundColor': '#10b981',
            }
        ]
    }


def get_deadline_compliance_chart_data(user, department_id=None, date_range=None) -> dict:
    """
    Returns Doughnut chart data for on-time vs late task completions.
    """
    m = get_deadline_metrics(user, department_id=department_id, date_range=date_range)
    return {
        'labels': [_('Before Deadline'), _('On Deadline'), _('After Deadline (Late)')],
        'datasets': [{
            'data': [
                m['completed_before_deadline'],
                m['completed_on_deadline'],
                m['completed_after_deadline'],
            ],
            'backgroundColor': ['#10b981', '#3b82f6', '#ef4444'],
        }]
    }


def get_signature_trends_chart_data(user, date_range=None) -> dict:
    """
    Returns time-series data for electronic signatures issued over time.
    """
    if not ElectronicSignature:
        return {'labels': [], 'datasets': []}

    tasks_qs = get_scoped_tasks(user, date_range=date_range)
    sigs = ElectronicSignature.objects.filter(task__in=tasks_qs, status='SIGNED')
    if date_range:
        sigs = sigs.filter(signed_at__gte=date_range[0], signed_at__lte=date_range[1])

    series = (
        sigs.annotate(day=TruncDate('signed_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    labels = [s['day'].strftime('%d %b') for s in series if s['day']]
    data = [s['count'] for s in series if s['day']]

    return {
        'labels': labels,
        'datasets': [{
            'label': _('Electronic Signatures'),
            'data': data,
            'borderColor': '#8b5cf6',
            'backgroundColor': 'rgba(139, 92, 246, 0.1)',
            'tension': 0.3,
            'fill': True,
        }]
    }
