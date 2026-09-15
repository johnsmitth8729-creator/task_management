from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from core.models import AuditLog, log_audit
from organization.models import Department, DepartmentResponsibility, Position


def assign_department_head(department: Department, head_user: User | None, actor: User, request=None):
    """
    Assigns a single official department head to a department.
    Enforces the rule: each department has strictly ONE department head.
    Automatically revokes the DEPARTMENT_HEAD role from the previous head or any duplicate heads.
    """
    old_head = department.head
    head_role, _ = Role.objects.get_or_create(
        code=Role.Codes.DEPARTMENT_HEAD,
        defaults={'name': 'Department Head', 'is_active': True},
    )
    emp_role, _ = Role.objects.get_or_create(
        code=Role.Codes.EMPLOYEE,
        defaults={'name': 'Employee', 'is_active': True},
    )

    if head_user:
        # If head_user was previously head of another department, clear that department's head
        Department.objects.filter(head=head_user).exclude(pk=department.pk).update(head=None)

        # Department Head must belong to the department
        if head_user.department_id != department.id:
            head_user.department = department
            head_user.save(update_fields=['department'])

        # Ensure head_user has the DEPARTMENT_HEAD role
        head_user.roles.add(head_role)

    # 1. Update department's head pointer
    department.head = head_user
    department.save(update_fields=['head', 'updated_at'])

    # 2. Enforce strictly ONE head: clean up any other users in this department holding DEPARTMENT_HEAD role
    other_heads_in_dept = User.objects.filter(department=department, roles=head_role)
    if head_user:
        other_heads_in_dept = other_heads_in_dept.exclude(pk=head_user.pk)

    for prev_head in other_heads_in_dept:
        # If not heading any other department, revoke head role and ensure employee role
        if not Department.objects.filter(head=prev_head).exclude(pk=department.pk).exists():
            prev_head.roles.remove(head_role)
            if not prev_head.roles.exists():
                prev_head.roles.add(emp_role)

    # 3. Clean up previous head if replaced or removed
    if old_head and old_head != head_user:
        if not Department.objects.filter(head=old_head).exists():
            old_head.roles.remove(head_role)
            if not old_head.roles.exists():
                old_head.roles.add(emp_role)

    action = (
        AuditLog.Actions.DEPARTMENT_HEAD_CHANGED
        if old_head and head_user
        else AuditLog.Actions.DEPARTMENT_HEAD_ASSIGNED
    )
    log_audit(
        actor=actor,
        action=action,
        target_repr=f"{department.name} -> {head_user.display_name if head_user else 'None'}",
        details={
            'department_id': str(department.id),
            'old_head': old_head.username if old_head else None,
            'new_head': head_user.username if head_user else None,
        },
        request=request,
    )
    return department


def assign_vice_rector_responsibility(
    vice_rector: User,
    department: Department,
    actor: User,
    start_date=None,
    request=None,
) -> DepartmentResponsibility:
    if not vice_rector.is_vice_rector:
        raise ValidationError(_('The selected user must have the Vice Rector role.'))

    # Check if active responsibility already exists
    existing = DepartmentResponsibility.objects.filter(
        vice_rector=vice_rector,
        department=department,
        is_active=True,
    ).first()
    if existing:
        return existing

    resp = DepartmentResponsibility.objects.create(
        vice_rector=vice_rector,
        department=department,
        start_date=start_date or timezone.now().date(),
        is_active=True,
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.VICE_RECTOR_RESPONSIBILITY_ASSIGNED,
        target_repr=f"{vice_rector.display_name} -> {department.name}",
        details={
            'responsibility_id': str(resp.id),
            'vice_rector': vice_rector.username,
            'department': department.name,
        },
        request=request,
    )
    return resp


def remove_vice_rector_responsibility(responsibility: DepartmentResponsibility, actor: User, request=None):
    responsibility.is_active = False
    responsibility.end_date = timezone.now().date()
    responsibility.save(update_fields=['is_active', 'end_date', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.VICE_RECTOR_RESPONSIBILITY_REMOVED,
        target_repr=f"{responsibility.vice_rector.display_name} -> {responsibility.department.name}",
        details={
            'responsibility_id': str(responsibility.id),
            'vice_rector': responsibility.vice_rector.username,
            'department': responsibility.department.name,
        },
        request=request,
    )
    return responsibility


def assign_rector(rector_user: User, actor: User, request=None):
    """
    Enforces the single Rector rule:
    There is strictly ONE active Rector in the university.
    Assigns the RECTOR role to rector_user and removes it from any other user.
    """
    rector_role, _ = Role.objects.get_or_create(
        code=Role.Codes.RECTOR,
        defaults={'name': 'Rector', 'is_active': True},
    )
    emp_role, _ = Role.objects.get_or_create(
        code=Role.Codes.EMPLOYEE,
        defaults={'name': 'Employee', 'is_active': True},
    )

    # Remove RECTOR role from all other users
    other_rectors = User.objects.filter(roles=rector_role).exclude(pk=rector_user.pk)
    for prev in other_rectors:
        prev.roles.remove(rector_role)
        if not prev.roles.exists():
            prev.roles.add(emp_role)

    # Assign RECTOR role to new rector
    rector_user.roles.add(rector_role)

    log_audit(
        actor=actor,
        action=AuditLog.Actions.ROLE_ASSIGNED,
        target_repr=f"Rector -> {rector_user.display_name}",
        details={'rector_id': str(rector_user.id), 'username': rector_user.username},
        request=request,
    )
    return rector_user


def assign_acting_rector(
    rector: User,
    acting_rector: User,
    actor: User,
    start_date=None,
    end_date=None,
    reason='',
    request=None,
):
    """
    Delegates Rector duties to a Vice Rector (Rektor v.b.).
    Deactivates any previous active delegations to maintain a single Acting Rector.
    """
    from organization.models import ActingRectorDelegation

    if not acting_rector.is_vice_rector:
        raise ValidationError(_('Only a Vice Rector can be designated as Acting Rector.'))

    # Deactivate existing active delegations
    ActingRectorDelegation.objects.filter(is_active=True).update(
        is_active=False,
        end_date=timezone.now().date(),
    )

    delegation = ActingRectorDelegation.objects.create(
        rector=rector,
        acting_rector=acting_rector,
        start_date=start_date or timezone.now().date(),
        end_date=end_date,
        reason=reason.strip(),
        is_active=True,
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.ROLE_ASSIGNED,
        target_repr=f"Acting Rector -> {acting_rector.display_name}",
        details={
            'delegation_id': str(delegation.id),
            'acting_rector': acting_rector.username,
            'start_date': str(delegation.start_date),
            'end_date': str(delegation.end_date) if delegation.end_date else None,
            'reason': delegation.reason,
        },
        request=request,
    )
    return delegation


def revoke_acting_rector(delegation, actor: User, request=None):
    """Revokes an acting rector delegation."""
    delegation.is_active = False
    delegation.end_date = timezone.now().date()
    delegation.save(update_fields=['is_active', 'end_date', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.ROLE_REMOVED,
        target_repr=f"Acting Rector Revoked -> {delegation.acting_rector.display_name}",
        details={'delegation_id': str(delegation.id), 'acting_rector': delegation.acting_rector.username},
        request=request,
    )
    return delegation
