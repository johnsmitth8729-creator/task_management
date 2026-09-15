from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from hr.services import get_hr_permission
from payroll.models import PayrollRecord, SalaryProfile


def get_payroll_permission(user: User, permission_field: str) -> bool:
    """
    Checks granular payroll permissions for Finance / HR / Technical Admin.
    Superadmin always has unrestricted access.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    # 1. Check direct PayrollPermissionConfig if present
    authority = getattr(user, 'payroll_authority', None)
    if authority:
        return getattr(authority, permission_field, False)

    # 2. Check HRPermissionConfig if field exists
    hr_auth = getattr(user, 'hr_authority', None)
    if hr_auth and hasattr(hr_auth, permission_field):
        return getattr(hr_auth, permission_field, False)

    # 3. Default operational policies for Finance role if no explicit config saved yet
    if user.is_finance:
        default_finance = {
            'can_view_payroll': True,
            'can_manage_salary': True,
            'can_manage_compensation': True,
            'can_calculate_payroll': True,
            'can_create_adjustment': True,
            'can_approve_payroll': False,
            'can_mark_paid': False,
            'can_view_payroll_reports': True,
            'can_manage_tax_rules': True,
            'can_manage_kpi_payroll_rules': True,
        }
        return default_finance.get(permission_field, False)

    return False


def can_view_payroll(user: User) -> bool:
    """University leadership, HR authority, and Finance can view aggregate overview or authorized payroll."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector or user.is_vice_rector or user.is_department_head:
        return True
    if user.is_finance:
        return get_payroll_permission(user, 'can_view_payroll')
    if user.is_hr:
        return get_hr_permission(user, 'can_view_payroll')
    return False


def can_manage_salary(user: User) -> bool:
    """Superadmin, authorized Finance, or authorized HR can manage base salary profiles."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_finance:
        return get_payroll_permission(user, 'can_manage_salary')
    if user.is_hr:
        return get_hr_permission(user, 'can_manage_salary')
    # Rector, Vice Rector, Department Head, Employee CANNOT edit/manage salaries
    return False


def can_manage_payroll(user: User) -> bool:
    """Superadmin, authorized Finance, or authorized HR can manage periods and run calculations."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_finance:
        return (
            get_payroll_permission(user, 'can_calculate_payroll')
            or get_payroll_permission(user, 'can_manage_compensation')
        )
    if user.is_hr:
        return get_hr_permission(user, 'can_manage_payroll')
    return False


def can_approve_payroll(user: User) -> bool:
    """Superadmin, Rector, authorized Finance, or authorized HR can approve payroll records."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_finance:
        return get_payroll_permission(user, 'can_approve_payroll')
    if user.is_hr:
        return get_hr_permission(user, 'can_approve_payroll')
    return False


def can_mark_paid(user: User) -> bool:
    """Superadmin, authorized Finance, or authorized HR can disburse / mark payroll paid."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_finance:
        return get_payroll_permission(user, 'can_mark_paid')
    if user.is_hr:
        return get_hr_permission(user, 'can_mark_paid')
    return False


def can_view_payroll_reports(user: User) -> bool:
    """Reports access: Superadmin, Rector, Vice Rector, Finance, or authorized HR."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector or user.is_vice_rector:
        return True
    if user.is_finance:
        return get_payroll_permission(user, 'can_view_payroll_reports')
    if user.is_hr:
        return get_hr_permission(user, 'can_view_payroll_reports')
    return False


def can_create_adjustment(user: User) -> bool:
    """Superadmin, authorized Finance, or authorized HR can create adjustments."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_finance:
        return get_payroll_permission(user, 'can_create_adjustment')
    if user.is_hr:
        return get_hr_permission(user, 'can_create_adjustment')
    return False


def can_view_user_salary(viewer: User, target_user: User) -> bool:
    """
    Object-level check for viewing an employee's salary and compensation details.
    STRICT PRIVACY RULES:
    - User can ALWAYS view their OWN salary (viewer.id == target_user.id).
    - Superadmin can view ANY salary.
    - Authorized Finance (can_manage_salary) can view.
    - Authorized HR (can_manage_salary) can view.
    - RECTOR CANNOT view individual salaries (aggregate only).
    - VICE RECTOR CANNOT view individual salaries (aggregate only).
    - DEPARTMENT HEAD CANNOT view individual salaries (aggregate only).
    - OTHER EMPLOYEES CANNOT view other employees' salaries.
    """
    if not viewer or not viewer.is_authenticated:
        return False
    if viewer.is_superuser:
        return True
    if viewer.id == target_user.id:
        return True
    if viewer.is_finance and get_payroll_permission(viewer, 'can_manage_salary'):
        return True
    if viewer.is_hr and get_hr_permission(viewer, 'can_manage_salary'):
        return True
    return False


def can_view_payroll_record(viewer: User, record: PayrollRecord) -> bool:
    """
    Object-level authorization to prevent IDOR on payroll records, payslips, and PDF downloads.
    STRICT PRIVACY RULES:
    - Employee can view their OWN approved or paid payroll records.
    - Superadmin can view ANY record.
    - Authorized Finance (can_view_payroll) can view.
    - Authorized HR (can_view_payroll) can view.
    - RECTOR CANNOT view individual payslips/records.
    - VICE RECTOR CANNOT view individual payslips/records.
    - DEPARTMENT HEAD CANNOT view individual payslips/records.
    - OTHER EMPLOYEES CANNOT view other employees' records.
    """
    if not viewer or not viewer.is_authenticated:
        return False
    if viewer.is_superuser:
        return True
    if record.employee_id == viewer.id:
        return record.status in [PayrollRecord.Status.APPROVED, PayrollRecord.Status.PAID]
    if viewer.is_finance and get_payroll_permission(viewer, 'can_view_payroll'):
        return True
    if viewer.is_hr and get_hr_permission(viewer, 'can_view_payroll'):
        return True
    return False


# ---------------------------------------------------------------------------
# View Mixins
# ---------------------------------------------------------------------------

class PayrollAccessRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_view_payroll(request.user):
            raise PermissionDenied(_('You do not have permission to view payroll.'))
        return super().dispatch(request, *args, **kwargs)


class SalaryManageRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_manage_salary(request.user):
            raise PermissionDenied(_('You do not have permission to manage employee salaries.'))
        return super().dispatch(request, *args, **kwargs)


class PayrollManageRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_manage_payroll(request.user):
            raise PermissionDenied(_('You do not have permission to manage payroll periods or calculations.'))
        return super().dispatch(request, *args, **kwargs)


class PayrollApproveRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_approve_payroll(request.user):
            raise PermissionDenied(_('You do not have permission to approve payroll.'))
        return super().dispatch(request, *args, **kwargs)


class ScopedPayrollRecordAccessMixin(AccessMixin):
    def get_payroll_record(self):
        pk = self.kwargs.get('pk') or self.kwargs.get('record_id')
        record = get_object_or_404(
            PayrollRecord.objects.select_related(
                'period',
                'employee',
                'employee__department',
                'employee__position',
                'employee__grade',
            ),
            pk=pk,
        )
        if not can_view_payroll_record(self.request.user, record):
            raise PermissionDenied(_('You do not have permission to view this payroll record.'))
        return record

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_payroll_record()
        return super().dispatch(request, *args, **kwargs)
