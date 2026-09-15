from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from hr.services import get_hr_permission
from kpi.models import KPIAssignment, KPIResult


def can_view_kpi_for_user(viewer: User, target_user: User) -> bool:
    if not viewer.is_authenticated:
        return False
    if viewer.is_superuser or viewer.is_rector:
        return True
    if viewer.id == target_user.id:
        return True
    if viewer.is_hr:
        return get_hr_permission(viewer, 'can_view_kpi')
    if viewer.is_vice_rector and target_user.department:
        return viewer.get_scoped_departments().filter(id=target_user.department_id).exists()
    if viewer.is_department_head and viewer.department_id and target_user.department_id == viewer.department_id:
        return True
    return False


def can_manage_kpi(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector or get_hr_permission(user, 'can_manage_kpi')


def can_approve_kpi(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector or get_hr_permission(user, 'can_approve_kpi')


def can_calculate_kpi(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector or get_hr_permission(user, 'can_manage_kpi')


def can_verify_kpi(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector or get_hr_permission(user, 'can_manage_kpi')


def can_rector_approve_kpi(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector


def can_rector_sign_kpi(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector


def can_request_kpi_correction(user: User, result: KPIResult) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.id == result.assignment.user_id:
        return True
    if user.is_department_head and user.department_id and result.assignment.user.department_id == user.department_id:
        return True
    return False


class KPIManageRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_manage_kpi(request.user):
            raise PermissionDenied(_('You do not have permission to manage KPI definitions or assignments.'))
        return super().dispatch(request, *args, **kwargs)


def can_view_kpi_catalog(user: User) -> bool:
    """KPI Catalog (definition list) is visible to leadership and HR — NOT plain employees."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_vice_rector or user.is_department_head:
        return True
    if user.is_hr:
        return get_hr_permission(user, 'can_view_kpi') or get_hr_permission(user, 'can_manage_kpi')
    return False


class KPIViewCatalogRequiredMixin(AccessMixin):
    """Blocks plain employees from accessing the KPI definition catalog."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_view_kpi_catalog(request.user):
            raise PermissionDenied(_('You do not have permission to view the KPI catalog.'))
        return super().dispatch(request, *args, **kwargs)


class ScopedKPIAssignmentAccessMixin(AccessMixin):
    def get_assignment(self):
        pk = self.kwargs.get('pk') or self.kwargs.get('assignment_id')
        assignment = get_object_or_404(KPIAssignment, pk=pk)
        if not can_view_kpi_for_user(self.request.user, assignment.user):
            raise PermissionDenied(_('You do not have permission to view or evaluate this KPI record.'))
        return assignment

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_assignment()
        return super().dispatch(request, *args, **kwargs)
