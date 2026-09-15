from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied


def can_manage_automation(user) -> bool:
    """Only Technical Superadmin has full authority to manage rules, SLA policies, and scheduler settings."""
    return user.is_authenticated and user.is_superuser


def can_view_automation_dashboard(user) -> bool:
    """Superadmin, Rector, and Vice Rectors can monitor the automation and SLA center."""
    if not user.is_authenticated:
        return False
    return (
        user.is_superuser or
        getattr(user, 'is_rector', False) or
        getattr(user, 'is_vice_rector', False)
    )


def can_manage_recurring_tasks(user) -> bool:
    """Superadmin and Rector can configure university recurring task schedules."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or getattr(user, 'is_rector', False)


class AutomationAccessRequiredMixin(UserPassesTestMixin):
    """View mixin requiring Superadmin, Rector, or Vice Rector authority."""
    def test_func(self):
        return can_view_automation_dashboard(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied("You do not have permission to view the Automation & SLA Center.")


class AutomationManagementRequiredMixin(UserPassesTestMixin):
    """View mixin requiring Technical Superadmin authority."""
    def test_func(self):
        return can_manage_automation(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied("Only Technical Administrators can modify automation rules and SLA policies.")
