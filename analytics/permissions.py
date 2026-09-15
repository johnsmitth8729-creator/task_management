from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from hr.services import get_hr_permission
from organization.models import Department
from payroll.permissions import get_payroll_permission


def can_view_executive_analytics(user: User) -> bool:
    """Rector, Vice Rector, and Superadmin can access executive analytics."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector or user.is_vice_rector


def can_view_department_analytics(user: User, department: Department | None = None) -> bool:
    """
    Checks if a user can view analytics for a specific department.
    - Superadmin / Rector: University-wide (any department)
    - Vice Rector: Assigned responsible departments only
    - Department Head: Own department only
    - Employee: False
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if not department:
        # Generic department list access
        return user.is_vice_rector or user.is_department_head
    if user.is_vice_rector:
        return user.department_responsibilities.filter(department=department, is_active=True).exists()
    if user.is_department_head and user.department:
        return user.department_id == department.id
    return False


def can_view_personal_analytics(viewer: User, target_user: User) -> bool:
    """
    Self-service personal performance or authorized supervisor check.
    """
    if not viewer or not viewer.is_authenticated or not target_user:
        return False
    if viewer.id == target_user.id:
        return True
    if viewer.is_superuser or viewer.is_rector:
        return True
    if viewer.is_vice_rector and target_user.department:
        return viewer.department_responsibilities.filter(
            department=target_user.department,
            is_active=True
        ).exists()
    if viewer.is_department_head and viewer.department and target_user.department:
        return viewer.department_id == target_user.department_id
    if viewer.is_hr:
        return get_hr_permission(viewer, 'can_view_analytics')
    return False


def can_view_hr_analytics(user: User) -> bool:
    """HR Managers, Rector, and Superadmin can access HR organizational analytics."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_hr:
        return True
    return False


def can_view_payroll_analytics(user: User) -> bool:
    """
    Finance Officers and Superadmin can access macro payroll analytics.
    Strictly preserves Phase 8 role governance and salary privacy.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_finance:
        return get_payroll_permission(user, 'can_view_payroll_reports')
    return False


def can_view_signature_analytics(user: User) -> bool:
    """Rector, Vice Rector, and Superadmin can view signature throughput."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector or user.is_vice_rector


def can_view_audit_analytics(user: User) -> bool:
    """Strictly technical Superadmin only."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser


def can_export_analytics_report(user: User, report_type: str, department_id: str | None = None) -> bool:
    """
    Validates export authorization based on report type and department scope.
    Prevents IDOR and unauthorized privilege escalation during file downloads.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    from analytics.models import SavedReportConfiguration
    rt = SavedReportConfiguration.ReportTypes

    # Department scope validation
    dept = None
    if department_id:
        try:
            dept = Department.objects.get(id=department_id, is_active=True)
        except (Department.DoesNotExist, ValueError):
            return False

    if report_type == rt.UNIVERSITY_TASKS:
        return user.is_rector or user.is_vice_rector
    elif report_type == rt.DEPARTMENT_PERFORMANCE:
        if dept:
            return can_view_department_analytics(user, dept)
        return user.is_rector or user.is_vice_rector or user.is_department_head
    elif report_type == rt.KPI_SUMMARY:
        if dept:
            return can_view_department_analytics(user, dept)
        return user.is_rector or user.is_vice_rector or user.is_department_head or user.is_hr
    elif report_type == rt.PAYROLL_ANALYTICS:
        return can_view_payroll_analytics(user)
    elif report_type == rt.SIGNATURE_AUDIT:
        return can_view_signature_analytics(user)
    elif report_type == rt.DEADLINE_COMPLIANCE:
        if dept:
            return can_view_department_analytics(user, dept)
        return user.is_rector or user.is_vice_rector or user.is_department_head
    elif report_type == rt.HR_DISTRIBUTION:
        return can_view_hr_analytics(user)

    return False


class AnalyticsAccessMixin(AccessMixin):
    """Mixin for views requiring general analytics access."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)
