from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from organization.models import Department


def can_view_department(user, department: Department) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_vice_rector:
        return user.department_responsibilities.filter(department=department, is_active=True).exists()
    if user.department_id == department.id:
        return True
    return False


def can_manage_department(user, department: Department | None = None) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector


def can_view_user(viewer: User, target_user: User) -> bool:
    if not viewer.is_authenticated:
        return False
    if target_user.is_superuser and not viewer.is_superuser:
        return False
    if viewer.is_superuser or viewer.can_act_as_rector or viewer.is_hr:
        return True
    if viewer.id == target_user.id:
        return True
    if viewer.is_vice_rector:
        if not target_user.department:
            return False
        return viewer.department_responsibilities.filter(
            department=target_user.department,
            is_active=True,
        ).exists()
    if viewer.is_department_head and viewer.department:
        return target_user.department_id == viewer.department_id
    return False


def can_edit_user(viewer: User, target_user: User) -> bool:
    if not viewer.is_authenticated:
        return False
    # User can edit own profile basic information
    if viewer.id == target_user.id:
        return True
    # Only superadmin and HR can edit other users
    if viewer.is_superuser:
        return True
    if viewer.is_hr and not target_user.is_superuser:
        return True
    return False


def can_delete_user(viewer: User, target_user: User) -> bool:
    if not viewer.is_authenticated:
        return False
    # User cannot delete own account
    if viewer.id == target_user.id:
        return False
    # Only superadmin and HR can delete other users
    if viewer.is_superuser:
        return True
    if viewer.is_hr and not target_user.is_superuser:
        return True
    return False


def can_manage_roles(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector


def can_manage_responsibilities(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector


class RectorRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_superuser or request.user.is_rector):
            raise PermissionDenied(_('Only the Rector or Technical Superadmin has permission to perform this action.'))
        return super().dispatch(request, *args, **kwargs)



class ScopedDepartmentAccessMixin(AccessMixin):
    def get_department(self):
        dept_id = self.kwargs.get('pk') or self.kwargs.get('department_id')
        dept = get_object_or_404(Department, pk=dept_id)
        if not can_view_department(self.request.user, dept):
            raise PermissionDenied(_('You do not have access to this department.'))
        return dept

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        # Verify department access on dispatch
        self.get_department()
        return super().dispatch(request, *args, **kwargs)


class ScopedUserAccessMixin(AccessMixin):
    def get_target_user(self):
        user_id = self.kwargs.get('pk') or self.kwargs.get('user_id')
        target_user = get_object_or_404(User, pk=user_id)
        if not can_view_user(self.request.user, target_user):
            raise PermissionDenied(_('You do not have access to this user profile.'))
        return target_user

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_target_user()
        return super().dispatch(request, *args, **kwargs)
