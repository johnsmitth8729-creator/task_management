from django.utils.translation import gettext as _

from accounts.models import User
from analytics.models import AnalyticsThresholdConfig
from core.models import AuditLog


def record_analytics_view_event(user: User, dashboard_type: str, ip_address: str | None = None, user_agent: str | None = None) -> AuditLog:
    """
    Records an analytics dashboard access event in the core AuditLog.
    """
    return AuditLog.objects.create(
        actor=user if user.is_authenticated else None,
        action=AuditLog.Actions.ANALYTICS_VIEWED,
        target_repr=f"Analytics: {dashboard_type}",
        ip_address=ip_address,
        details={'dashboard_type': dashboard_type, 'user_agent': user_agent or ''}
    )


def record_report_export_event(user: User, report_type: str, export_format: str, ip_address: str | None = None, user_agent: str | None = None) -> AuditLog:
    """
    Records an analytics report export event in the core AuditLog.
    """
    return AuditLog.objects.create(
        actor=user if user.is_authenticated else None,
        action=AuditLog.Actions.ANALYTICS_EXPORTED,
        target_repr=f"Report Export: {report_type} ({export_format.upper()})",
        ip_address=ip_address,
        details={'report_type': report_type, 'format': export_format, 'user_agent': user_agent or ''}
    )


def get_executive_alerts(metrics: dict, bottlenecks: dict, config: AnalyticsThresholdConfig | None = None) -> list[dict]:
    """
    Evaluates key performance metrics against configurable institutional thresholds.
    Returns a list of alert dictionaries for the executive attention panel.
    """
    if not config:
        config = AnalyticsThresholdConfig.get_active()

    alerts = []

    # 1. Overdue tasks alert
    overdue_count = metrics.get('overdue_tasks', 0)
    if overdue_count > config.max_acceptable_overdue_tasks:
        alerts.append({
            'type': 'danger',
            'icon': 'bi-exclamation-triangle-fill',
            'title': _('High Overdue Volume'),
            'message': _('Currently %(count)d overdue tasks require immediate executive follow-up.') % {'count': overdue_count},
            'threshold': f"> {config.max_acceptable_overdue_tasks}",
            'metric': overdue_count,
        })

    # 2. Completion rate alert
    comp_rate = metrics.get('completion_rate', 0.0)
    if metrics.get('total_tasks', 0) > 0 and comp_rate < float(config.min_completion_rate_percent):
        alerts.append({
            'type': 'warning',
            'icon': 'bi-graph-down-arrow',
            'title': _('Low Task Completion Rate'),
            'message': _('Completion rate (%(rate).1f%%) is currently below target (%(target).1f%%).') % {
                'rate': comp_rate, 'target': float(config.min_completion_rate_percent)
            },
            'threshold': f"< {config.min_completion_rate_percent}%",
            'metric': f"{comp_rate}%",
        })

    # 3. On-time delivery rate alert
    ontime_rate = metrics.get('ontime_rate', 0.0)
    if metrics.get('completed_tasks', 0) > 0 and ontime_rate < float(config.min_ontime_rate_percent):
        alerts.append({
            'type': 'warning',
            'icon': 'bi-clock-history',
            'title': _('On-Time Delivery Decline'),
            'message': _('On-time completion (%(rate).1f%%) is below the minimum threshold (%(target).1f%%).') % {
                'rate': ontime_rate, 'target': float(config.min_ontime_rate_percent)
            },
            'threshold': f"< {config.min_ontime_rate_percent}%",
            'metric': f"{ontime_rate}%",
        })

    # 4. First approval bottleneck alert
    fa_wait = bottlenecks.get('avg_first_approval_wait_days', 0.0)
    if fa_wait > float(config.max_first_approval_wait_days):
        alerts.append({
            'type': 'info',
            'icon': 'bi-hourglass-split',
            'title': _('First Approval Queue Bottleneck'),
            'message': _('Department Head approval turnaround averaging %(days).1f days.') % {'days': fa_wait},
            'threshold': f"> {config.max_first_approval_wait_days} {_('days')}",
            'metric': f"{fa_wait} {_('days')}",
        })

    # 5. Pending signatures alert
    pending_sig = metrics.get('pending_signature', 0)
    if pending_sig > 5:
        alerts.append({
            'type': 'info',
            'icon': 'bi-pen-fill',
            'title': _('Tasks Awaiting Signature'),
            'message': _('%(count)d completed tasks approved and awaiting electronic signature.') % {'count': pending_sig},
            'threshold': "> 5",
            'metric': pending_sig,
        })

    return alerts
