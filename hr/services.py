from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from core.models import AuditLog, log_audit
from hr.models import EmployeeGrade, HRPermissionConfig
from organization.models import Department, Position


def get_hr_permission(user: User, permission_field: str) -> bool:
    """
    Checks if the user has a specific granular HR permission.
    Superadmin and Rector always have full authority.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_hr:
        authority = getattr(user, 'hr_authority', None)
        if authority:
            return getattr(authority, permission_field, False)
        # Default fallback permissions for HR role if config not yet explicitly saved
        default_allowed = {
            'can_view_employees': True,
            'can_create_employees': False,
            'can_edit_employees': True,
            'can_deactivate_employees': False,
            'can_assign_department': True,
            'can_assign_position': True,
            'can_assign_grade': True,
            'can_assign_supervisor': True,
            'can_manage_departments': False,
            'can_assign_department_head': False,
            'can_assign_vice_rector_responsibility': False,
            'can_view_kpi': True,
            'can_manage_kpi': False,
            'can_approve_kpi': False,
        }
        return default_allowed.get(permission_field, False)
    return False


def get_eligible_supervisors(department: Department = None, exclude_user: User = None):
    """
    Returns users who are eligible to act as a direct supervisor for an employee.
    Rules:
    - is_superuser=False (Technical superadmin is excluded from employee hierarchy).
    - is_active=True and employment_status in [ACTIVE, ON_LEAVE].
    - Must hold management authority (position.can_supervise=True OR role in [RECTOR, VICE_RECTOR, DEPARTMENT_HEAD]).
    - exclude_user is excluded, along with all recursive subordinates of exclude_user (to prevent cycles).
    - If department is provided:
        - Includes eligible managers belonging to this department,
        - Includes Vice Rectors assigned responsibility over this department,
        - Includes Rector.
    """
    from django.db.models import Q
    from organization.models import DepartmentResponsibility

    base_qs = User.objects.filter(
        is_superuser=False,
        is_active=True,
        employment_status__in=[User.EmploymentStatus.ACTIVE, User.EmploymentStatus.ON_LEAVE],
    ).filter(
        Q(position__can_supervise=True) |
        Q(roles__code__in=[Role.Codes.RECTOR, Role.Codes.VICE_RECTOR, Role.Codes.DEPARTMENT_HEAD])
    ).distinct()

    if exclude_user and exclude_user.id:
        # Collect all recursive subordinates
        exclude_ids = {exclude_user.id}
        subordinates = list(User.objects.filter(supervisor_id=exclude_user.id).values_list('id', flat=True))
        while subordinates:
            exclude_ids.update(subordinates)
            subordinates = list(User.objects.filter(supervisor_id__in=subordinates).values_list('id', flat=True))
        base_qs = base_qs.exclude(id__in=exclude_ids)

    if department:
        # Department heads, departmental managers, vice rectors responsible for department, and rector
        dept_manager_q = Q(department=department)
        rector_q = Q(roles__code=Role.Codes.RECTOR)
        vr_ids = DepartmentResponsibility.objects.filter(
            department=department, is_active=True
        ).values_list('vice_rector_id', flat=True)
        vr_q = Q(id__in=vr_ids)
        # Also include unassigned global vice rectors
        global_vr_q = Q(roles__code=Role.Codes.VICE_RECTOR, department__isnull=True)

        base_qs = base_qs.filter(dept_manager_q | rector_q | vr_q | global_vr_q)

    return base_qs.select_related('department', 'position').order_by('first_name', 'last_name', 'username')


def validate_supervisor_assignment(user_or_none: User, supervisor: User, department: Department = None):
    """
    Validates supervisor eligibility, authority, anti-tampering, department compatibility, and cycle prevention.
    """
    if not supervisor:
        return

    if supervisor.is_superuser:
        raise ValidationError({'supervisor': _('Technical Superadmin cannot be assigned as an employee supervisor.')})

    if not supervisor.is_active or supervisor.employment_status not in [User.EmploymentStatus.ACTIVE, User.EmploymentStatus.ON_LEAVE]:
        raise ValidationError({'supervisor': _('Selected supervisor is inactive or terminated.')})

    if not supervisor.can_supervise:
        raise ValidationError({'supervisor': _('Selected employee is not eligible to be a supervisor (does not hold management authority).')})

    if user_or_none and user_or_none.id:
        if supervisor.id == user_or_none.id:
            raise ValidationError({'supervisor': _('An employee cannot be their own supervisor.')})

        # Recursive cycle detection
        curr = supervisor
        visited = {user_or_none.id}
        while curr:
            if curr.id in visited:
                raise ValidationError({'supervisor': _('Cyclic supervisor hierarchy detected. An employee cannot report to their subordinate.')})
            visited.add(curr.id)
            curr = curr.supervisor

    # Department compatibility check
    if department and supervisor.department and supervisor.department != department:
        # Allowed only if supervisor is Rector or Vice Rector responsible for this department
        if supervisor.is_rector:
            return
        if supervisor.is_vice_rector:
            from organization.models import DepartmentResponsibility
            is_responsible = DepartmentResponsibility.objects.filter(
                vice_rector=supervisor, department=department, is_active=True
            ).exists()
            if not is_responsible:
                raise ValidationError({'supervisor': _('Vice Rector is not assigned responsibility for the selected department.')})
            return
        raise ValidationError({'supervisor': _('Selected supervisor belongs to a different department and cannot supervise staff in this department.')})


@transaction.atomic
def create_employee(actor: User, data: dict, request=None) -> User:
    if not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_create_employees')):
        raise PermissionDenied(_('You do not have permission to create employees.'))

    username = data.get('username')
    email = data.get('email')
    password = data.get('password', 'ChangeMe12345!')

    if User.objects.filter(username=username).exists():
        raise ValidationError({'username': _('A user with that username already exists.')})
    if User.objects.filter(email=email).exists():
        raise ValidationError({'email': _('A user with that email already exists.')})

    dept = data.get('department')
    pos = data.get('position')
    grade = data.get('grade')
    supervisor = data.get('supervisor')

    if supervisor:
        if not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_supervisor')):
            raise PermissionDenied(_('You do not have permission to assign supervisors.'))
        validate_supervisor_assignment(None, supervisor, dept)

    if dept and not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_department')):
        raise PermissionDenied(_('You do not have permission to assign departments.'))

    if pos and not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_position')):
        raise PermissionDenied(_('You do not have permission to assign positions.'))

    if grade and not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_grade')):
        raise PermissionDenied(_('You do not have permission to assign grades.'))

    user = User(
        username=username,
        email=email,
        first_name=data.get('first_name', ''),
        last_name=data.get('last_name', ''),
        phone=data.get('phone', ''),
        department=dept,
        position=pos,
        grade=grade,
        supervisor=supervisor,
        employment_status=data.get('employment_status', User.EmploymentStatus.ACTIVE),
        employment_start_date=data.get('employment_start_date', timezone.now().date()),
        employment_end_date=data.get('employment_end_date'),
        is_active=True,
    )
    user.set_password(password)
    user.save()


    # Assign default Employee role if no roles provided
    roles = data.get('roles')
    if roles:
        user.roles.set(roles)
        for r in user.roles.all():
            action = AuditLog.Actions.FINANCE_ROLE_ASSIGNED if r.code == Role.Codes.FINANCE else AuditLog.Actions.ROLE_ASSIGNED
            log_audit(
                actor=actor,
                action=action,
                target_repr=user.display_name,
                details={'role': r.code, 'username': user.username},
                request=request,
            )
    else:
        emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee', 'is_active': True})
        user.roles.add(emp_role)
        log_audit(
            actor=actor,
            action=AuditLog.Actions.ROLE_ASSIGNED,
            target_repr=user.display_name,
            details={'role': emp_role.code, 'username': user.username},
            request=request,
        )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.USER_CREATED,
        target_repr=user.display_name,
        details={
            'username': user.username,
            'email': user.email,
            'department': user.department.name if user.department else None,
            'position': user.position.name if user.position else None,
            'grade': user.grade.code if user.grade else None,
        },
        request=request,
    )
    return user


@transaction.atomic
def update_employee(actor: User, user: User, data: dict, request=None) -> User:
    if not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_edit_employees') or actor.id == user.id):
        raise PermissionDenied(_('You do not have permission to edit this employee.'))

    old_dept = user.department
    old_pos = user.position
    old_grade = user.grade
    old_supervisor = user.supervisor
    old_status = user.employment_status

    if 'first_name' in data:
        user.first_name = data['first_name']
    if 'last_name' in data:
        user.last_name = data['last_name']
    if 'email' in data:
        user.email = data['email']
    if 'phone' in data:
        user.phone = data['phone']

    # Organizational assignments (guarded by specific granular HR permissions)
    if 'department' in data and (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_department')):
        new_dept = data['department']
        if new_dept != old_dept:
            user.department = new_dept
            log_audit(
                actor=actor,
                action=AuditLog.Actions.EMPLOYEE_DEPARTMENT_CHANGED,
                target_repr=user.display_name,
                details={'old_department': old_dept.name if old_dept else None, 'new_department': new_dept.name if new_dept else None},
                request=request,
            )

    if 'position' in data and (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_position')):
        new_pos = data['position']
        if new_pos != old_pos:
            user.position = new_pos
            log_audit(
                actor=actor,
                action=AuditLog.Actions.EMPLOYEE_POSITION_CHANGED,
                target_repr=user.display_name,
                details={'old_position': old_pos.name if old_pos else None, 'new_position': new_pos.name if new_pos else None},
                request=request,
            )

    if 'grade' in data and (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_grade')):
        new_grade = data['grade']
        if new_grade != old_grade:
            user.grade = new_grade
            log_audit(
                actor=actor,
                action=AuditLog.Actions.EMPLOYEE_GRADE_CHANGED,
                target_repr=user.display_name,
                details={'old_grade': old_grade.code if old_grade else None, 'new_grade': new_grade.code if new_grade else None},
                request=request,
            )

    if 'supervisor' in data and (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_supervisor')):
        new_sup = data['supervisor']
        target_dept = data.get('department', user.department)
        if new_sup:
            validate_supervisor_assignment(user, new_sup, target_dept)
        if new_sup != old_supervisor:
            user.supervisor = new_sup
            log_audit(
                actor=actor,
                action=AuditLog.Actions.EMPLOYEE_SUPERVISOR_CHANGED,
                target_repr=user.display_name,
                details={'old_supervisor': old_supervisor.username if old_supervisor else None, 'new_supervisor': new_sup.username if new_sup else None},
                request=request,
            )


    if 'employment_status' in data:
        new_status = data['employment_status']
        if new_status != old_status:
            user.employment_status = new_status
            if new_status == User.EmploymentStatus.INACTIVE or new_status == User.EmploymentStatus.TERMINATED:
                user.is_active = False
            elif new_status == User.EmploymentStatus.ACTIVE:
                user.is_active = True
            log_audit(
                actor=actor,
                action=AuditLog.Actions.EMPLOYEE_STATUS_CHANGED,
                target_repr=user.display_name,
                details={'old_status': old_status, 'new_status': new_status},
                request=request,
            )

    if 'employment_start_date' in data:
        user.employment_start_date = data['employment_start_date']
    if 'employment_end_date' in data:
        user.employment_end_date = data['employment_end_date']

    if 'roles' in data and (actor.is_superuser or actor.is_rector):
        old_roles = set(user.roles.values_list('code', flat=True))
        user.roles.set(data['roles'])
        new_roles = set(user.roles.values_list('code', flat=True))
        added = new_roles - old_roles
        removed = old_roles - new_roles
        for r_code in added:
            action = AuditLog.Actions.FINANCE_ROLE_ASSIGNED if r_code == Role.Codes.FINANCE else AuditLog.Actions.ROLE_ASSIGNED
            log_audit(
                actor=actor,
                action=action,
                target_repr=user.display_name,
                details={'role': r_code, 'username': user.username},
                request=request,
            )
        for r_code in removed:
            log_audit(
                actor=actor,
                action=AuditLog.Actions.ROLE_REMOVED,
                target_repr=user.display_name,
                details={'role': r_code, 'username': user.username},
                request=request,
            )

    user.save()
    log_audit(
        actor=actor,
        action=AuditLog.Actions.USER_UPDATED,
        target_repr=user.display_name,
        details={'username': user.username},
        request=request,
    )
    return user


@transaction.atomic
def deactivate_employee(actor: User, user: User, request=None) -> User:
    if not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_deactivate_employees')):
        raise PermissionDenied(_('You do not have permission to deactivate employees.'))
    if actor.id == user.id:
        raise ValidationError(_('You cannot deactivate your own account.'))

    user.is_active = False
    user.employment_status = User.EmploymentStatus.INACTIVE
    user.save(update_fields=['is_active', 'employment_status', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.USER_DEACTIVATED,
        target_repr=user.display_name,
        details={'username': user.username, 'status': 'INACTIVE'},
        request=request,
    )
    return user


@transaction.atomic
def activate_employee(actor: User, user: User, request=None) -> User:
    if not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_edit_employees')):
        raise PermissionDenied(_('You do not have permission to activate employees.'))

    user.is_active = True
    user.employment_status = User.EmploymentStatus.ACTIVE
    user.save(update_fields=['is_active', 'employment_status', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.USER_ACTIVATED,
        target_repr=user.display_name,
        details={'username': user.username, 'status': 'ACTIVE'},
        request=request,
    )
    return user


@transaction.atomic
def create_grade(actor: User, data: dict, request=None) -> EmployeeGrade:
    if not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_grade')):
        raise PermissionDenied(_('You do not have permission to manage grades.'))

    grade = EmployeeGrade.objects.create(
        name=data['name'],
        code=data['code'],
        description=data.get('description', ''),
        rank=data.get('rank', 1),
        is_active=data.get('is_active', True),
    )
    log_audit(
        actor=actor,
        action=AuditLog.Actions.GRADE_CREATED,
        target_repr=f"{grade.code} — {grade.name}",
        details={'code': grade.code, 'rank': grade.rank},
        request=request,
    )
    return grade


@transaction.atomic
def update_grade(actor: User, grade: EmployeeGrade, data: dict, request=None) -> EmployeeGrade:
    if not (actor.is_superuser or actor.is_rector or get_hr_permission(actor, 'can_assign_grade')):
        raise PermissionDenied(_('You do not have permission to manage grades.'))

    grade.name = data.get('name', grade.name)
    grade.code = data.get('code', grade.code)
    grade.description = data.get('description', grade.description)
    grade.rank = data.get('rank', grade.rank)
    if 'is_active' in data:
        grade.is_active = data['is_active']
    grade.save()

    log_audit(
        actor=actor,
        action=AuditLog.Actions.GRADE_UPDATED,
        target_repr=f"{grade.code} — {grade.name}",
        details={'code': grade.code, 'rank': grade.rank},
        request=request,
    )
    return grade


@transaction.atomic
def configure_hr_authority(actor: User, target_user: User, permissions_data: dict, request=None) -> HRPermissionConfig:
    if not (actor.is_superuser or actor.is_rector):
        raise PermissionDenied(_('Only the Rector or Technical Superadmin can configure HR authority permissions.'))

    authority, _ = HRPermissionConfig.objects.get_or_create(user=target_user)

    for field in [
        'can_view_employees',
        'can_create_employees',
        'can_edit_employees',
        'can_deactivate_employees',
        'can_assign_department',
        'can_assign_position',
        'can_assign_grade',
        'can_assign_supervisor',
        'can_manage_departments',
        'can_assign_department_head',
        'can_assign_vice_rector_responsibility',
        'can_view_kpi',
        'can_manage_kpi',
        'can_approve_kpi',
        'can_view_payroll',
        'can_manage_salary',
        'can_create_adjustment',
        'can_manage_payroll',
        'can_approve_payroll',
        'can_mark_paid',
        'can_view_payroll_reports',
    ]:
        if field in permissions_data:
            setattr(authority, field, bool(permissions_data[field]))

    authority.save()

    log_audit(
        actor=actor,
        action=AuditLog.Actions.HR_PERMISSION_CHANGED,
        target_repr=f"HR Authority -> {target_user.display_name}",
        details={'user': target_user.username, 'permissions': permissions_data},
        request=request,
    )
    return authority
