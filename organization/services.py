from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from core.models import AuditLog, log_audit
from organization.models import Department, DepartmentResponsibility, Position


def assign_department_head(department: Department, head_user: User | None, actor: User, request=None):
    if head_user:
        # Department Head must belong to the department
        if head_user.department_id != department.id:
            head_user.department = department
            head_user.save(update_fields=['department'])

        # Ensure user has the DEPARTMENT_HEAD role
        head_role, _ = Role.objects.get_or_create(
            code=Role.Codes.DEPARTMENT_HEAD,
            defaults={'name': 'Department Head', 'is_active': True},
        )
        head_user.roles.add(head_role)

    old_head = department.head
    department.head = head_user
    department.save(update_fields=['head', 'updated_at'])

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
