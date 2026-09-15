from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from hr.services import get_hr_permission


def can_view_employee_profile(viewer: User, target_user: User) -> bool:
    if not viewer.is_authenticated:
        return False
    if viewer.is_superuser or viewer.is_rector or viewer.is_hr:
        return True
    if viewer.id == target_user.id:
        return True
    if viewer.is_vice_rector and target_user.department:
        return viewer.get_scoped_departments().filter(id=target_user.department_id).exists()
    if viewer.is_department_head and viewer.department_id and target_user.department_id == viewer.department_id:
        return True
    return False


class HRRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_superuser or request.user.is_rector or request.user.is_hr):
            raise PermissionDenied(_('You do not have access to HR management functions.'))
        return super().dispatch(request, *args, **kwargs)


class HRPermissionRequiredMixin(AccessMixin):
    permission_field = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.permission_field:
            raise ValueError('permission_field must be set on HRPermissionRequiredMixin')
        if not (request.user.is_superuser or request.user.is_rector or get_hr_permission(request.user, self.permission_field)):
            raise PermissionDenied(_('You do not have the required HR permission to perform this action.'))
        return super().dispatch(request, *args, **kwargs)


class ScopedEmployeeProfileAccessMixin(AccessMixin):
    def get_target_user(self):
        pk = self.kwargs.get('pk') or self.kwargs.get('user_id')
        target_user = get_object_or_404(User, pk=pk)
        if not can_view_employee_profile(self.request.user, target_user):
            raise PermissionDenied(_('You do not have permission to view this employee profile.'))
        return target_user

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_target_user()
        return super().dispatch(request, *args, **kwargs)
