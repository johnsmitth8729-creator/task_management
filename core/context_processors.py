from core.models import Notification


def navigation_context(request):
    """
    Provides centralized two-level navigation data for the platform:
    - sidebar_navigation_groups / sidebar_sections: Top-level sections for the global sidebar.
    - active_navigation_section: Currently active top-level section.
    - contextual_navigation_items: Authorized child functions for the active section (for contextual top navigation).
    Computed once per request.
    """
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {
            'sidebar_navigation_groups': [],
            'sidebar_sections': [],
            'active_navigation_section': None,
            'contextual_navigation_items': [],
        }

    from core.navigation import get_navigation_data
    nav_data = get_navigation_data(request)
    return {
        'sidebar_navigation_groups': nav_data['sections'],
        'sidebar_sections': nav_data['sections'],
        'active_navigation_section': nav_data['active_section'],
        'contextual_navigation_items': nav_data['contextual_items'],
    }


def active_year_context(request):
    """
    Provides the active working/academic year selected in session.
    Defaults to the current calendar year (e.g., 2026).
    Only includes years that have actual data in the database,
    plus the current calendar year, the currently selected active year,
    and the next upcoming calendar year (to allow transitioning to a new academic/operational year).
    Years without data (e.g. 2024, 2025) are never displayed.
    """
    from django.utils import timezone
    current_year = timezone.now().year
    
    session_year = request.session.get('active_year') if hasattr(request, 'session') else None
    if session_year is not None:
        try:
            active_year = int(session_year)
        except (ValueError, TypeError):
            active_year = current_year
    else:
        active_year = current_year

    years_with_data = set()
    try:
        from tasks.models import Task
        for d in Task.objects.dates('created_at', 'year'):
            years_with_data.add(d.year)
    except Exception:
        pass

    try:
        from operations.models import UniversityDocument
        for d in UniversityDocument.objects.dates('created_at', 'year'):
            years_with_data.add(d.year)
        for d in UniversityDocument.objects.dates('effective_date', 'year'):
            years_with_data.add(d.year)
    except Exception:
        pass

    try:
        from core.models import AuditLog
        for d in AuditLog.objects.dates('created_at', 'year'):
            years_with_data.add(d.year)
    except Exception:
        pass

    # Available years: only years with actual data + current calendar year + next calendar year + active_year
    years_set = set(years_with_data)
    years_set.add(current_year)
    years_set.add(current_year + 1)
    if active_year:
        years_set.add(active_year)

    available_years = sorted(list(years_set))

    # Structured metadata list for template rendering
    years_info = []
    for yr in available_years:
        years_info.append({
            'year': yr,
            'is_active': yr == active_year,
            'is_current': yr == current_year,
            'is_archive': yr < current_year,
            'is_future': yr > current_year,
            'has_data': yr in years_with_data,
        })

    return {
        'active_year': active_year,
        'current_calendar_year': current_year,
        'available_years': available_years,
        'available_years_info': years_info,
        'years_with_data': years_with_data,
        'is_historical_year': active_year < current_year,
        'is_future_year': active_year > current_year,
    }


def notifications_context(request):
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {
            'unread_notifications_count': 0,
            'recent_notifications': [],
        }

    unread_count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).count()

    recent_notifications = Notification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')[:5]

    return {
        'unread_notifications_count': unread_count,
        'recent_notifications': recent_notifications,
    }


def hr_authority_context(request):
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {
            'can_manage_kpi': False,
            'can_view_kpi': False,
            'can_view_payroll': False,
            'can_manage_salary': False,
            'can_manage_payroll': False,
            'can_approve_payroll': False,
            'can_mark_paid': False,
            'can_view_payroll_reports': False,
            'is_finance': False,
        }

    user = request.user

    # Superadmin: unrestricted technical access
    if user.is_superuser:
        return {
            'can_manage_kpi': True,
            'can_view_kpi': True,
            'can_view_payroll': True,
            'can_manage_salary': True,
            'can_manage_payroll': True,
            'can_approve_payroll': True,
            'can_mark_paid': True,
            'can_view_payroll_reports': True,
            'is_finance': False,
        }

    # Finance role: operational payroll authority (not salary management for Rector)
    if user.is_finance:
        from payroll.permissions import get_payroll_permission
        return {
            'can_manage_kpi': False,
            'can_view_kpi': False,
            'can_view_payroll': get_payroll_permission(user, 'can_view_payroll'),
            'can_manage_salary': get_payroll_permission(user, 'can_manage_salary'),
            'can_manage_payroll': get_payroll_permission(user, 'can_calculate_payroll'),
            'can_approve_payroll': get_payroll_permission(user, 'can_approve_payroll'),
            'can_mark_paid': get_payroll_permission(user, 'can_mark_paid'),
            'can_view_payroll_reports': get_payroll_permission(user, 'can_view_payroll_reports'),
            'is_finance': True,
        }

    if user.is_hr:
        from hr.services import get_hr_permission
        return {
            'can_manage_kpi': get_hr_permission(user, 'can_manage_kpi'),
            'can_view_kpi': get_hr_permission(user, 'can_view_kpi'),
            'can_view_payroll': get_hr_permission(user, 'can_view_payroll'),
            'can_manage_salary': get_hr_permission(user, 'can_manage_salary'),
            'can_manage_payroll': get_hr_permission(user, 'can_manage_payroll'),
            'can_approve_payroll': get_hr_permission(user, 'can_approve_payroll'),
            'can_mark_paid': get_hr_permission(user, 'can_mark_paid'),
            'can_view_payroll_reports': get_hr_permission(user, 'can_view_payroll_reports'),
            'is_finance': False,
        }

    # Rector: university-wide AGGREGATE visibility only; CANNOT manage/edit salaries
    if user.is_rector:
        return {
            'can_manage_kpi': True,
            'can_view_kpi': True,
            'can_view_payroll': True,       # can see dashboard aggregate
            'can_manage_salary': False,     # CANNOT edit individual salaries
            'can_manage_payroll': False,    # CANNOT run calculations
            'can_approve_payroll': True,    # Rector can approve payroll
            'can_mark_paid': False,         # Cannot disburse (Finance does this)
            'can_view_payroll_reports': True,
            'is_finance': False,
        }

    # Vice Rector & Department Heads: aggregate view only
    is_leadership = user.is_vice_rector or user.is_department_head
    return {
        'can_manage_kpi': False,
        'can_view_kpi': is_leadership,
        'can_view_payroll': is_leadership,
        'can_manage_salary': False,
        'can_manage_payroll': False,
        'can_approve_payroll': False,
        'can_mark_paid': False,
        'can_view_payroll_reports': is_leadership,
        'is_finance': False,
    }


