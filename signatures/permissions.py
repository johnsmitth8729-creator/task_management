from django.utils.translation import gettext_lazy as _

from accounts.models import User
from tasks.models import Task, TaskApproval


def can_sign_task(user: User, task: Task) -> tuple[bool, str]:
    """
    Validates whether the given authenticated user has authority to electronically sign
    the completed task.

    Returns:
        (is_allowed: bool, reason_if_denied: str)
    """
    if not user.is_authenticated:
        return False, str(_('Authentication is required to sign tasks.'))

    # 1. Validate task lifecycle state
    if task.status != Task.Status.COMPLETED:
        return False, str(_('Tasks can only be signed after reaching final completed status.'))

    # 2. Check for existing active signature (prevent duplicate signing)
    if task.signatures.filter(status='SIGNED').exists():
        return False, str(_('This task has already been electronically signed.'))

    # 3. Check for valid final approval record
    has_final_approval = task.approvals.filter(
        stage=TaskApproval.Stage.FINAL_APPROVAL,
        decision=TaskApproval.Decision.APPROVED,
    ).exists()
    if not has_final_approval:
        return False, str(_('Task must have an approved final approval record before signing.'))

    # 4. Role authority: only the Rector (university head), Acting Rector, or superadmin may sign.
    #    Regular Vice Rectors (without acting rector delegation) and Department Heads are denied.
    if user.is_superuser:
        return True, ''

    if user.can_act_as_rector:
        return True, ''

    if user.is_vice_rector:
        return False, str(_('Vice Rectors are not authorized to electronically sign tasks. Only the Rector may sign (or delegated Acting Rector).'))

    # All other roles (Department Head, Employee, HR, Finance) are strictly denied
    return False, str(_('You do not have authorization to electronically sign tasks.'))


def can_revoke_signature(user: User, signature) -> bool:
    """
    Only Technical Superadmin, Rector, or Acting Rector can revoke an electronic signature record.
    """
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.can_act_as_rector


def can_view_signature_internal(user: User, signature) -> bool:
    """
    Internal permission to view complete signature details and audit history.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_vice_rector:
        dept_id = signature.task.responsible_department_id
        return bool(dept_id and user.get_scoped_departments().filter(id=dept_id).exists())
    if user.is_department_head:
        return signature.task.responsible_department_id == user.department_id
    if user.is_employee:
        return signature.task.assignments.filter(user=user).exists()
    return False
