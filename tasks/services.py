from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from core.models import AuditLog, Notification, create_notification, log_audit
from organization.models import Department
from tasks.models import (
    RecurringTask,
    SubTask,
    Task,
    TaskApproval,
    TaskAssignment,
    TaskDeadlineExtension,
    TaskDependency,
    TaskHistory,
    TaskNote,
    TaskSubmission,
    TaskTemplate,
    TaskType,
)


def get_scoped_tasks(user: User, include_archived: bool = False, year: int | None = None) -> QuerySet[Task]:
    """
    Returns the authorized base QuerySet of Task objects for the given user,
    automatically scoped to the active working year.
    """
    if not user.is_authenticated:
        return Task.objects.none()

    if user.is_superuser or user.is_rector:
        qs = Task.objects.all()
    elif user.is_vice_rector:
        scoped_depts = user.get_scoped_departments()
        qs = Task.objects.filter(
            Q(responsible_department__in=scoped_depts) | Q(creator=user)
        ).distinct()
    elif user.is_department_head and user.department_id:
        qs = Task.objects.filter(responsible_department_id=user.department_id)
    elif user.is_employee:
        qs = Task.objects.filter(assignments__user=user).distinct()
    else:
        qs = Task.objects.none()

    if not include_archived:
        qs = qs.exclude(status=Task.Status.ARCHIVED)

    # Active working year scoping
    effective_year = year
    if effective_year is None:
        from core.middleware import get_current_active_year
        effective_year = get_current_active_year()

    if effective_year:
        qs = qs.filter(created_at__year=effective_year)

    return qs


@transaction.atomic
def create_task(
    actor: User,
    title: str,
    description: str = '',
    responsible_department: Department | None = None,
    task_type: TaskType | None = None,
    priority: str = Task.Priority.MEDIUM,
    complexity: str = Task.Complexity.SIMPLE,
    start_date=None,
    deadline=None,
    status: str = Task.Status.CREATED,
    initial_assignees: list[User] | None = None,
    primary_assignee: User | None = None,
    secondary_departments: list[Department] | None = None,
    request=None,
) -> Task:
    if not actor.is_authenticated:
        raise ValidationError(_('Authentication is required to create a task.'))

    from tasks.permissions import can_create_task
    if not can_create_task(actor):
        raise ValidationError(_('You do not have permission to create tasks.'))

    # Department Head can only create tasks for their own department
    if actor.is_department_head and not (actor.is_superuser or actor.can_act_as_rector or actor.is_vice_rector):
        if not responsible_department:
            responsible_department = actor.department
        elif actor.department_id and responsible_department.id != actor.department_id:
            raise ValidationError(_('Department Head can only create tasks for their own department.'))

    # Validate department scope for Vice Rector
    if actor.is_vice_rector and responsible_department and not (actor.is_superuser or actor.can_act_as_rector):
        if not actor.get_scoped_departments().filter(id=responsible_department.id).exists():
            raise ValidationError(_('You cannot assign tasks to a department outside your scope.'))

    # Validate dates
    if start_date and deadline and start_date > deadline:
        raise ValidationError(_('Start date cannot be later than deadline.'))

    task = Task(
        title=title.strip(),
        description=description.strip(),
        creator=actor,
        responsible_department=responsible_department,
        task_type=task_type,
        priority=priority,
        complexity=complexity,
        start_date=start_date,
        deadline=deadline,
        status=status,
    )
    task.save()

    # If operating in an active working year (e.g., 2027) while server clock is 2026,
    # align created_at with the active year so it belongs to that year's workflow.
    from core.middleware import get_current_active_year
    active_year = get_current_active_year()
    if active_year:
        try:
            ay = int(active_year)
            if task.created_at.year != ay and ay != timezone.now().year:
                new_created_at = task.created_at.replace(year=ay)
                Task.objects.filter(id=task.id).update(created_at=new_created_at)
                task.created_at = new_created_at
        except (ValueError, TypeError):
            pass

    # Add explicitly specified secondary departments
    if secondary_departments:
        for s_dept in secondary_departments:
            if responsible_department and s_dept.id == responsible_department.id:
                continue
            if actor.is_department_head and not (actor.is_superuser or actor.can_act_as_rector or actor.is_vice_rector):
                raise ValidationError(_('Department Head can only create tasks for their own department.'))
            if actor.is_vice_rector and not (actor.is_superuser or actor.can_act_as_rector):
                if not actor.get_scoped_departments().filter(id=s_dept.id).exists():
                    raise ValidationError(_('You cannot assign tasks to a department outside your scope.'))
            task.secondary_departments.add(s_dept)

    # Create initial assignments if provided
    if initial_assignees:
        for u in initial_assignees:
            # Superadmin cannot be assigned by non-superadmin
            if u.is_superuser and not actor.is_superuser:
                raise ValidationError(_("Superadmin foydalanuvchiga vazifa biriktirib bo‘lmaydi."))

            # Subordinate restriction: Vice Rector and Department Head cannot assign to Rector or Vice Rectors
            if not (actor.is_superuser or actor.can_act_as_rector):
                if u.is_rector:
                    raise ValidationError(_("Rektorga vazifa biriktirish mumkin emas."))
                if u.is_vice_rector and not actor.is_superuser:
                    raise ValidationError(_("Prorektorga vazifa biriktirish mumkin emas."))

            # Scope checks for Department Head
            if actor.is_department_head and not (actor.is_superuser or actor.can_act_as_rector or actor.is_vice_rector):
                if u.department_id != actor.department_id:
                    raise ValidationError(_('Department Head can only assign employees within their own department.'))

            # Scope checks for Vice Rector
            if actor.is_vice_rector and not (actor.is_superuser or actor.can_act_as_rector):
                if u.department_id and not actor.get_scoped_departments().filter(id=u.department_id).exists():
                    raise ValidationError(_('Vice Rector can only assign employees within their supervised departments.'))

            # If assignee is from a different department, add to secondary_departments
            if u.department and responsible_department and u.department_id != responsible_department.id:
                task.secondary_departments.add(u.department)

            is_prim = (primary_assignee is not None and u.id == primary_assignee.id)
            TaskAssignment.objects.create(
                task=task,
                user=u,
                assigned_by=actor,
                is_primary=is_prim,
            )
        if task.status == Task.Status.CREATED and task.assignments.exists():
            task.status = Task.Status.ASSIGNED
            task.save(update_fields=['status'])

    # Log History
    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_CREATED,
        new_value={
            'title': task.title,
            'department': str(task.responsible_department) if task.responsible_department else None,
            'priority': task.priority,
            'complexity': task.complexity,
            'status': task.status,
            'deadline': str(task.deadline) if task.deadline else None,
        },
    )

    # Log Audit
    log_audit(
        actor=actor,
        action=AuditLog.Actions.TASK_CREATED,
        target_repr=f"{task.task_number}: {task.title}",
        details={
            'task_id': str(task.id),
            'department_id': str(responsible_department.id) if responsible_department else None,
            'priority': priority,
            'complexity': complexity,
        },
        request=request,
    )

    return task


@transaction.atomic
def update_task(actor: User, task: Task, data: dict, request=None) -> Task:
    old_values = {}
    updated_fields = []

    # Check for specific significant changes
    if 'title' in data and data['title'] != task.title:
        old_values['title'] = task.title
        task.title = data['title']
        updated_fields.append('title')

    if 'description' in data and data['description'] != task.description:
        old_values['description'] = task.description
        task.description = data['description']
        updated_fields.append('description')

    if 'priority' in data and data['priority'] != task.priority:
        TaskHistory.objects.create(
            task=task,
            actor=actor,
            event_type=TaskHistory.EventType.PRIORITY_CHANGED,
            old_value={'priority': task.priority},
            new_value={'priority': data['priority']},
        )
        task.priority = data['priority']
        updated_fields.append('priority')

    if 'complexity' in data and data['complexity'] != task.complexity:
        TaskHistory.objects.create(
            task=task,
            actor=actor,
            event_type=TaskHistory.EventType.COMPLEXITY_CHANGED,
            old_value={'complexity': task.complexity},
            new_value={'complexity': data['complexity']},
        )
        task.complexity = data['complexity']
        updated_fields.append('complexity')

    if 'deadline' in data and data['deadline'] != task.deadline:
        TaskHistory.objects.create(
            task=task,
            actor=actor,
            event_type=TaskHistory.EventType.DEADLINE_CHANGED,
            old_value={'deadline': str(task.deadline) if task.deadline else None},
            new_value={'deadline': str(data['deadline']) if data['deadline'] else None},
        )
        task.deadline = data['deadline']
        updated_fields.append('deadline')
        log_audit(
            actor=actor,
            action=AuditLog.Actions.TASK_DEADLINE_CHANGED,
            target_repr=f"{task.task_number}: {task.title}",
            details={'old_deadline': str(task.deadline), 'new_deadline': str(data['deadline'])},
            request=request,
        )

    if 'responsible_department' in data and data['responsible_department'] != task.responsible_department:
        TaskHistory.objects.create(
            task=task,
            actor=actor,
            event_type=TaskHistory.EventType.DEPARTMENT_CHANGED,
            old_value={'department': str(task.responsible_department) if task.responsible_department else None},
            new_value={'department': str(data['responsible_department']) if data['responsible_department'] else None},
        )
        task.responsible_department = data['responsible_department']
        updated_fields.append('responsible_department')

    if 'task_type' in data and data['task_type'] != task.task_type:
        task.task_type = data['task_type']
        updated_fields.append('task_type')

    if 'start_date' in data and data['start_date'] != task.start_date:
        task.start_date = data['start_date']
        updated_fields.append('start_date')

    if 'progress' in data and data['progress'] != task.progress:
        old_progress = task.progress
        task.progress = max(0, min(100, int(data['progress'])))
        updated_fields.append('progress')
        TaskHistory.objects.create(
            task=task,
            actor=actor,
            event_type=TaskHistory.EventType.PROGRESS_UPDATED,
            old_value={'progress': old_progress},
            new_value={'progress': task.progress},
        )

    if updated_fields:
        task.save(update_fields=updated_fields + ['updated_at'])
        TaskHistory.objects.create(
            task=task,
            actor=actor,
            event_type=TaskHistory.EventType.TASK_UPDATED,
            new_value={'updated_fields': updated_fields},
        )
        log_audit(
            actor=actor,
            action=AuditLog.Actions.TASK_UPDATED,
            target_repr=f"{task.task_number}: {task.title}",
            details={'updated_fields': updated_fields},
            request=request,
        )

    return task


@transaction.atomic
def transition_status(actor: User, task: Task, new_status: str, request=None) -> Task:
    allowed_transitions = {
        Task.Status.DRAFT: [Task.Status.CREATED, Task.Status.CANCELLED],
        Task.Status.CREATED: [Task.Status.ASSIGNED, Task.Status.IN_PROGRESS, Task.Status.CANCELLED],
        Task.Status.ASSIGNED: [Task.Status.IN_PROGRESS, Task.Status.CANCELLED],
        Task.Status.IN_PROGRESS: [Task.Status.COMPLETED, Task.Status.CANCELLED],
        Task.Status.COMPLETED: [Task.Status.ARCHIVED],
        Task.Status.CANCELLED: [Task.Status.ARCHIVED],
        Task.Status.ARCHIVED: [],
    }

    current = task.status
    if new_status not in allowed_transitions.get(current, []):
        raise ValidationError(_(f"Transition from {current} to {new_status} is not permitted."))

    old_status = task.status
    task.status = new_status

    if new_status == Task.Status.COMPLETED:
        task.completed_at = timezone.now()
        task.progress = 100
    elif new_status == Task.Status.ARCHIVED:
        task.archived_at = timezone.now()

    task.save()

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.STATUS_CHANGED,
        old_value={'status': old_status},
        new_value={'status': new_status},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.TASK_STATUS_CHANGED,
        target_repr=f"{task.task_number}: {task.title}",
        details={'old_status': old_status, 'new_status': new_status},
        request=request,
    )

    return task


@transaction.atomic
def cancel_task(actor: User, task: Task, cancellation_reason: str, request=None) -> Task:
    from tasks.permissions import can_cancel_task
    if not can_cancel_task(actor, task):
        raise ValidationError(_('You do not have permission to cancel this task.'))

    if not cancellation_reason or not cancellation_reason.strip():
        raise ValidationError(_('A cancellation reason is required.'))

    if task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('This task cannot be cancelled in its current status.'))

    old_status = task.status
    task.status = Task.Status.CANCELLED
    task.cancelled_at = timezone.now()
    task.cancelled_by = actor
    task.cancellation_reason = cancellation_reason.strip()
    task.save()

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_CANCELLED,
        old_value={'status': old_status},
        new_value={'status': Task.Status.CANCELLED, 'reason': task.cancellation_reason},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.TASK_CANCELLED,
        target_repr=f"{task.task_number}: {task.title}",
        details={'reason': task.cancellation_reason, 'previous_status': old_status},
        request=request,
    )

    # Automatic targeted KPI recalculation for affected assignees
    try:
        from kpi.calculation import recalculate_employee_period_kpis
        from kpi.models import KPIPeriod
        open_periods = list(KPIPeriod.objects.filter(is_active=True, status=KPIPeriod.Status.OPEN))
        for a in task.assignments.all().select_related('user'):
            for p in open_periods:
                recalculate_employee_period_kpis(a.user, p, actor=actor)
    except Exception:
        pass

    return task


@transaction.atomic
def archive_task(actor: User, task: Task, request=None) -> Task:
    from tasks.permissions import can_archive_task
    if not can_archive_task(actor, task):
        raise ValidationError(_('You do not have permission to archive this task.'))

    if task.status not in (Task.Status.COMPLETED, Task.Status.CANCELLED):
        raise ValidationError(_('Only completed or cancelled tasks can be archived.'))

    old_status = task.status
    task.status = Task.Status.ARCHIVED
    task.archived_at = timezone.now()
    task.save()

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_ARCHIVED,
        old_value={'status': old_status},
        new_value={'status': Task.Status.ARCHIVED},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.TASK_ARCHIVED,
        target_repr=f"{task.task_number}: {task.title}",
        details={'previous_status': old_status},
        request=request,
    )

    return task


@transaction.atomic
def assign_task(
    actor: User,
    task: Task,
    users: list[User],
    primary_user: User | None = None,
    request=None,
) -> list[TaskAssignment]:
    from tasks.permissions import can_assign_task, is_task_in_submission_or_approval
    if is_task_in_submission_or_approval(task) and not (actor.is_superuser or actor.can_act_as_rector):
        raise ValidationError(_("Vazifa topshirilgan (ko‘rib chiqish jarayonida) bo‘lganligi sababli ijrochilarni o‘zgartirib bo‘lmaydi."))

    if not can_assign_task(actor, task):
        raise ValidationError(_("Sizda ushbu vazifaga ijrochi biriktirish huquqi yo‘q."))

    created_assignments = []
    for u in users:
        if not u.is_active:
            raise ValidationError(_(f"User {u.display_name} is inactive and cannot be assigned."))

        # Nobody can assign tasks to technical superadmin except superadmin
        if u.is_superuser and not actor.is_superuser:
            raise ValidationError(_("Superadmin foydalanuvchiga vazifa biriktirib bo‘lmaydi."))

        # Subordinate restriction: Vice Rector and Department Head cannot assign to Rector or Vice Rectors
        if not (actor.is_superuser or actor.can_act_as_rector):
            if u.is_rector:
                raise ValidationError(_("Rektorga vazifa biriktirish mumkin emas."))
            if u.is_vice_rector and not actor.is_superuser:
                raise ValidationError(_("Prorektorga vazifa biriktirish mumkin emas."))

        # Department scoping rules:
        if actor.is_department_head and not (actor.is_superuser or actor.can_act_as_rector or actor.is_vice_rector):
            if actor.department_id and u.department_id != actor.department_id:
                raise ValidationError(_(f"Bo‘lim boshlig‘i faqat o‘z bo‘limi xodimlariga vazifa yuklay oladi ({u.display_name})."))
        elif actor.is_vice_rector and not (actor.is_superuser or actor.can_act_as_rector):
            scoped_depts = actor.get_scoped_departments()
            if u.department_id and not scoped_depts.filter(id=u.department_id).exists():
                raise ValidationError(_(f"Foydalanuvchi {u.display_name} sizning biriktirilgan bo‘limlaringiz doirasiga kirmaydi."))
            if u.department and task.responsible_department_id and u.department_id != task.responsible_department_id:
                task.secondary_departments.add(u.department)
        elif actor.is_superuser or actor.can_act_as_rector:
            # Cross-department allowed: add secondary department if different
            if u.department and task.responsible_department_id and u.department_id != task.responsible_department_id:
                task.secondary_departments.add(u.department)

        is_prim = (primary_user is not None and u.id == primary_user.id)
        defaults = {'assigned_by': actor, 'is_primary': is_prim}
        if task.status == Task.Status.COMPLETED:
            defaults['assignment_status'] = TaskAssignment.AssignmentStatus.APPROVED
            defaults['progress'] = 100
        elif task.status == Task.Status.CANCELLED:
            defaults['assignment_status'] = TaskAssignment.AssignmentStatus.REJECTED

        existing = task.assignments.filter(user=u).first()
        if existing is None:
            defaults['assigned_by'] = actor
            assignment = TaskAssignment.objects.create(
                task=task,
                user=u,
                **defaults,
            )
        else:
            for key, val in defaults.items():
                setattr(existing, key, val)
            if not existing.assigned_by:
                existing.assigned_by = actor
            existing.save()
            assignment = existing
        created_assignments.append(assignment)

    # If primary_user was set, ensure other existing assignments have is_primary=False
    if primary_user:
        task.assignments.exclude(user=primary_user).update(is_primary=False)

    # Transition from CREATED to ASSIGNED if applicable
    if task.status == Task.Status.CREATED and created_assignments:
        task.status = Task.Status.ASSIGNED
        task.save(update_fields=['status'])

    assigned_names = [u.display_name for u in users]
    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_ASSIGNED,
        new_value={'assignees': assigned_names, 'primary': primary_user.display_name if primary_user else None},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.TASK_ASSIGNED,
        target_repr=f"{task.task_number}: {task.title}",
        details={'assigned_users': [str(u.id) for u in users]},
        request=request,
    )

    return created_assignments


@transaction.atomic
def unassign_user(actor: User, task: Task, assignment: TaskAssignment, request=None):
    from tasks.permissions import can_unassign_user
    if not can_unassign_user(actor, task, assignment):
        if assignment.user_id == actor.id:
            raise ValidationError(_('Biriktirilgan xodim o‘zini vazifadan chiqara olmaydi.'))
        raise ValidationError(_('Sizda ushbu xodimni vazifadan chiqarish huquqi yo‘q.'))

    user_name = assignment.user.display_name
    assignment.delete()

    # If no assignments remain and task was ASSIGNED, switch back to CREATED
    if not task.assignments.exists() and task.status == Task.Status.ASSIGNED:
        task.status = Task.Status.CREATED
        task.save(update_fields=['status'])

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_UNASSIGNED,
        new_value={'unassigned_user': user_name},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.TASK_UNASSIGNED,
        target_repr=f"{task.task_number}: {task.title}",
        details={'unassigned_user': user_name},
        request=request,
    )


@transaction.atomic
def create_subtask(
    actor: User,
    task: Task,
    title: str,
    description: str = '',
    status: str = SubTask.Status.TODO,
    progress: int = 0,
    assignee: User | None = None,
    deadline=None,
    request=None,
) -> SubTask:
    subtask = SubTask.objects.create(
        parent_task=task,
        title=title.strip(),
        description=description.strip(),
        status=status,
        progress=max(0, min(100, progress)),
        assignee=assignee,
        deadline=deadline,
    )

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.SUBTASK_CREATED,
        new_value={'subtask_title': subtask.title, 'assignee': assignee.display_name if assignee else None},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.SUBTASK_CREATED,
        target_repr=f"Subtask '{subtask.title}' for {task.task_number}",
        details={'subtask_id': str(subtask.id)},
        request=request,
    )

    return subtask


@transaction.atomic
def add_dependency(
    actor: User,
    task: Task,
    depends_on: Task,
    dependency_type: str = TaskDependency.DependencyType.FINISH_TO_START,
    request=None,
) -> TaskDependency:
    if task.id == depends_on.id:
        raise ValidationError(_('A task cannot depend on itself.'))

    # Check for direct reverse dependency (cycle prevention)
    if TaskDependency.objects.filter(task=depends_on, depends_on=task).exists():
        raise ValidationError(_('Circular dependency detected between these tasks.'))

    # Check if duplicate
    if TaskDependency.objects.filter(task=task, depends_on=depends_on).exists():
        raise ValidationError(_('This dependency relationship already exists.'))

    dep = TaskDependency.objects.create(
        task=task,
        depends_on=depends_on,
        dependency_type=dependency_type,
    )

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.DEPENDENCY_ADDED,
        new_value={'depends_on': depends_on.task_number, 'type': dependency_type},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.DEPENDENCY_CREATED,
        target_repr=f"{task.task_number} depends on {depends_on.task_number}",
        details={'dependency_id': str(dep.id)},
        request=request,
    )

    return dep


@transaction.atomic
def remove_dependency(actor: User, dependency: TaskDependency, request=None):
    task = dependency.task
    dep_number = dependency.depends_on.task_number
    dependency.delete()

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.DEPENDENCY_REMOVED,
        new_value={'removed_dependency': dep_number},
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.DEPENDENCY_REMOVED,
        target_repr=f"{task.task_number} no longer depends on {dep_number}",
        request=request,
    )


# ===========================================================================
# PHASE 4 — Employee Workflow Services
# ===========================================================================

@transaction.atomic
def accept_assignment(actor: User, assignment: TaskAssignment, request=None) -> TaskAssignment:
    """
    Employee accepts their assigned task.
    ASSIGNED → IN_PROGRESS (assignment level).
    Task status → IN_PROGRESS if it was ASSIGNED.
    """
    from django.db import DatabaseError
    from django.db.models import F

    if assignment.user_id != actor.id:
        raise ValidationError(_('You can only accept your own assignment.'))

    if assignment.assignment_status != TaskAssignment.AssignmentStatus.ASSIGNED:
        raise ValidationError(_('This assignment has already been accepted or is no longer available.'))

    if not actor.is_active:
        raise ValidationError(_('Inactive users cannot accept assignments.'))

    # Lock the row to prevent double-accept
    locked = TaskAssignment.objects.select_for_update().select_related('task').get(pk=assignment.pk)
    if locked.assignment_status != TaskAssignment.AssignmentStatus.ASSIGNED:
        raise ValidationError(_('This assignment has already been accepted.'))

    if locked.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('Cannot accept assignment on a completed or cancelled task.'))

    locked.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
    locked.accepted_at = timezone.now()
    locked.save(update_fields=['assignment_status', 'accepted_at', 'updated_at'])
    assignment.assignment_status = locked.assignment_status
    assignment.accepted_at = locked.accepted_at

    task = locked.task
    # Move task to IN_PROGRESS if it was ASSIGNED
    if task.status == Task.Status.ASSIGNED:
        task.status = Task.Status.IN_PROGRESS
        task.save(update_fields=['status', 'updated_at'])

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_ACCEPTED,
        new_value={
            'assignment_id': str(locked.id),
            'accepted_by': actor.display_name,
            'accepted_at': locked.accepted_at.isoformat(),
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.ASSIGNMENT_ACCEPTED,
        target_repr=f"{task.task_number}: accepted by {actor.display_name}",
        details={'assignment_id': str(locked.id), 'task_id': str(task.id)},
        request=request,
    )

    return locked


def sync_task_progress(task: Task) -> int:
    """
    Recalculates and persists the overall parent Task.progress percentage based on its assignments.
    - If a primary assignee exists with progress > 0, their progress is prioritized.
    - Otherwise, if assignments with progress > 0 exist, uses the average of active assignments.
    - Ensures Rector, Vice Rector, Department Head, and Employee dashboards reflect the updated percentage.
    """
    assignments = task.assignments.exclude(assignment_status=TaskAssignment.AssignmentStatus.REJECTED)
    if not assignments.exists():
        return task.progress

    primary_assign = assignments.filter(is_primary=True).first()
    if primary_assign and primary_assign.progress > 0:
        calculated_progress = primary_assign.progress
    else:
        progressing = assignments.filter(progress__gt=0)
        if progressing.exists():
            from django.db.models import Avg
            avg_val = progressing.aggregate(avg=Avg('progress'))['avg']
            calculated_progress = int(round(avg_val or 0))
        else:
            calculated_progress = 0

    calculated_progress = max(0, min(100, calculated_progress))

    if task.progress != calculated_progress:
        task.progress = calculated_progress
        update_fields = ['progress', 'updated_at']
        if task.status in (Task.Status.CREATED, Task.Status.ASSIGNED) and calculated_progress > 0:
            task.status = Task.Status.IN_PROGRESS
            update_fields.append('status')
        task.save(update_fields=update_fields)

    return task.progress


@transaction.atomic
def update_assignment_progress(
    actor: User, assignment: TaskAssignment, new_progress: int, request=None
) -> TaskAssignment:
    """Employee updates their own assignment progress (0–100)."""
    if assignment.user_id != actor.id:
        raise ValidationError(_('You can only update your own assignment progress.'))

    if assignment.assignment_status != TaskAssignment.AssignmentStatus.IN_PROGRESS:
        raise ValidationError(_('Progress can only be updated on in-progress assignments.'))

    new_progress = max(0, min(100, int(new_progress)))
    old_progress = assignment.progress

    if new_progress == old_progress:
        return assignment

    assignment.progress = new_progress
    assignment.save(update_fields=['progress', 'updated_at'])

    # Synchronize parent task's overall progress percentage for leadership & department heads
    sync_task_progress(assignment.task)

    TaskHistory.objects.create(
        task=assignment.task,
        actor=actor,
        event_type=TaskHistory.EventType.ASSIGNMENT_PROGRESS_UPDATED,
        old_value={'progress': old_progress},
        new_value={
            'progress': new_progress,
            'assignment_id': str(assignment.id),
            'employee': actor.display_name,
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.ASSIGNMENT_PROGRESS_UPDATED,
        target_repr=f"{assignment.task.task_number}: {old_progress}% → {new_progress}%",
        details={'assignment_id': str(assignment.id), 'old': old_progress, 'new': new_progress},
        request=request,
    )

    return assignment


@transaction.atomic
def add_task_note(
    actor: User,
    task: Task,
    content: str,
    assignment: TaskAssignment | None = None,
    request=None,
    visibility: str | None = None,
) -> TaskNote:
    """Add a work note to a task (scoped to assignment if provided)."""
    content = content.strip()
    if not content:
        raise ValidationError(_('Note content cannot be empty.'))
    if len(content) > 5000:
        raise ValidationError(_('Note content cannot exceed 5000 characters.'))

    if not visibility or visibility not in TaskNote.Visibility.values:
        visibility = TaskNote.Visibility.EMPLOYEE

    note = TaskNote.objects.create(
        task=task,
        assignment=assignment,
        author=actor,
        content=content,
        visibility=visibility,
    )

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_NOTE_CREATED,
        new_value={
            'note_id': str(note.id),
            'author': actor.display_name,
            'preview': content[:100],
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.NOTE_CREATED,
        target_repr=f"Note on {task.task_number} by {actor.display_name}",
        details={'note_id': str(note.id), 'task_id': str(task.id)},
        request=request,
    )

    return note


def get_visible_task_notes(user: User, task: Task) -> QuerySet[TaskNote]:
    """
    Return queryset of TaskNote instances visible to the given user for the task.
    - Superusers, Rector, and Vice Rector see all notes.
    - Department heads see employee notes, department head notes, and their own notes.
    - Employees see employee-visible notes and their own notes.
    """
    if not user.is_authenticated:
        return TaskNote.objects.none()

    qs = (
        TaskNote.objects
        .filter(task=task)
        .select_related('author', 'author__position', 'author__department', 'assignment', 'assignment__user')
        .order_by('-created_at')
    )

    if user.is_superuser or user.is_rector or user.is_vice_rector:
        return qs

    if user.is_department_head:
        return qs.filter(
            Q(author=user) |
            Q(visibility__in=[TaskNote.Visibility.EMPLOYEE, TaskNote.Visibility.DEPARTMENT_HEAD])
        )

    return qs.filter(
        Q(author=user) |
        Q(visibility=TaskNote.Visibility.EMPLOYEE)
    )


@transaction.atomic
def start_rework(actor: User, assignment: TaskAssignment, request=None) -> TaskAssignment:
    """
    Employee resumes / starts rework on a rejected assignment.
    assignment status: REJECTED → IN_PROGRESS
    Parent task status: reverts to IN_PROGRESS if it was ASSIGNED, CREATED, or COMPLETED.
    Logs TaskHistory (TASK_REWORK_STARTED) and AuditLog.
    """
    from tasks.permissions import can_start_rework
    if not can_start_rework(actor, assignment):
        raise ValidationError(_('You do not have permission to start rework on this assignment.'))

    locked = TaskAssignment.objects.select_for_update().select_related('task', 'user').get(pk=assignment.pk)
    if locked.assignment_status != TaskAssignment.AssignmentStatus.REJECTED:
        raise ValidationError(_('Only rejected assignments can be resumed for rework.'))

    task = locked.task
    if task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('Cannot start rework on a closed, cancelled, or archived task.'))

    old_status = locked.assignment_status
    locked.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
    locked.save(update_fields=['assignment_status', 'updated_at'])
    assignment.assignment_status = locked.assignment_status

    # Ensure parent task is IN_PROGRESS
    if task.status in (Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.COMPLETED):
        task.status = Task.Status.IN_PROGRESS
        task.completed_at = None
        task.save(update_fields=['status', 'completed_at', 'updated_at'])

    sync_task_progress(task)

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_REWORK_STARTED,
        old_value={'assignment_status': old_status},
        new_value={
            'assignment_id': str(locked.id),
            'resumed_by': actor.display_name,
            'assignment_status': TaskAssignment.AssignmentStatus.IN_PROGRESS,
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.TASK_REWORK_STARTED,
        target_repr=f"{task.task_number}: rework started by {actor.display_name}",
        details={'assignment_id': str(locked.id), 'task_id': str(task.id)},
        request=request,
    )

    # Notify Department Head
    if task.responsible_department and task.responsible_department.head:
        create_notification(
            recipient=task.responsible_department.head,
            notification_type=Notification.NotificationType.GENERAL,
            title=_('Task Rework Started'),
            message=_('{employee} started rework on {task_num}.').format(
                employee=actor.display_name,
                task_num=task.task_number,
            ),
            task=task,
            link=f"/workflow/assignments/{locked.id}/",
        )

    return locked


@transaction.atomic
def submit_assignment(
    actor: User, assignment: TaskAssignment, submission_text: str, request=None
) -> TaskSubmission:
    """
    Employee submits their completed work for first approval.
    assignment status: IN_PROGRESS (or REJECTED) → SUBMITTED
    Creates a versioned TaskSubmission record (v1, v2, v3...).
    Past submissions remain immutable.
    """
    submission_text = submission_text.strip()
    if not submission_text:
        raise ValidationError(_('Submission text is required.'))
    if len(submission_text) > 10000:
        raise ValidationError(_('Submission text cannot exceed 10,000 characters.'))

    # Lock assignment for concurrency safety
    locked = TaskAssignment.objects.select_for_update().select_related('task').get(pk=assignment.pk)
    if locked.user_id != actor.id and not actor.is_superuser:
        raise ValidationError(_('You can only submit your own assignment.'))

    if locked.assignment_status not in (
        TaskAssignment.AssignmentStatus.IN_PROGRESS,
        TaskAssignment.AssignmentStatus.REJECTED,
    ):
        raise ValidationError(_('Only in-progress or rework assignments can be submitted.'))

    if locked.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('Cannot submit assignment on a completed or cancelled task.'))

    task = locked.task

    # If submitted directly from REJECTED without prior explicit start_rework, record rework event
    if locked.assignment_status == TaskAssignment.AssignmentStatus.REJECTED:
        TaskHistory.objects.create(
            task=task,
            actor=actor,
            event_type=TaskHistory.EventType.TASK_REWORK_STARTED,
            old_value={'assignment_status': TaskAssignment.AssignmentStatus.REJECTED},
            new_value={
                'assignment_id': str(locked.id),
                'resumed_by': actor.display_name,
                'assignment_status': TaskAssignment.AssignmentStatus.IN_PROGRESS,
            },
        )
        log_audit(
            actor=actor,
            action=AuditLog.Actions.TASK_REWORK_STARTED,
            target_repr=f"{task.task_number}: rework resumed by {actor.display_name}",
            details={'assignment_id': str(locked.id), 'task_id': str(task.id)},
            request=request,
        )

    # Determine next version number (v1, v2, v3...)
    latest_version = (
        TaskSubmission.objects.filter(assignment=locked).order_by('-version').values_list('version', flat=True).first()
    ) or 0

    submission = TaskSubmission.objects.create(
        task=task,
        assignment=locked,
        submitted_by=actor,
        submission_text=submission_text,
        submitted_at=timezone.now(),
        version=latest_version + 1,
        status=TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL,
    )

    # Update assignment status and ensure progress is 100% upon submission
    locked.assignment_status = TaskAssignment.AssignmentStatus.SUBMITTED
    locked.progress = 100
    locked.save(update_fields=['assignment_status', 'progress', 'updated_at'])
    assignment.assignment_status = locked.assignment_status
    assignment.progress = locked.progress

    sync_task_progress(task)

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.TASK_SUBMISSION_CREATED,
        new_value={
            'submission_id': str(submission.id),
            'version': submission.version,
            'submitted_by': actor.display_name,
            'submitted_at': submission.submitted_at.isoformat(),
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.ASSIGNMENT_SUBMITTED,
        target_repr=f"{task.task_number}: submitted by {actor.display_name} (v{submission.version})",
        details={
            'submission_id': str(submission.id),
            'assignment_id': str(locked.id),
            'version': submission.version,
        },
        request=request,
    )

    # Notify Department Head
    if task.responsible_department and task.responsible_department.head:
        create_notification(
            recipient=task.responsible_department.head,
            notification_type=Notification.NotificationType.TASK_SUBMITTED,
            title=_('Task Submitted for First Approval'),
            message=_('{employee} submitted {task_num} for first approval.').format(
                employee=actor.display_name,
                task_num=task.task_number,
            ),
            task=task,
            link=f"/workflow/dept/submissions/{submission.id}/",
        )

    return submission


# ===========================================================================
# PHASE 5 — Management Approval, Rejection & Deadline Extension Services
# ===========================================================================

@transaction.atomic
def first_approve_assignment(
    actor: User, assignment: TaskAssignment, notes: str = '', request=None
):
    """
    Department Head grants first approval.
    assignment status: SUBMITTED → SECOND_APPROVAL
    TaskSubmission: PENDING_FIRST_APPROVAL → FIRST_APPROVED
    Creates TaskApproval(Stage=FIRST_APPROVAL, Decision=APPROVED).
    """
    from tasks.permissions import can_first_approve_assignment
    if not can_first_approve_assignment(actor, assignment):
        raise ValidationError(_('You do not have permission to grant first approval on this assignment.'))

    locked_assign = TaskAssignment.objects.select_for_update().select_related('task', 'user').get(pk=assignment.pk)
    if locked_assign.assignment_status != TaskAssignment.AssignmentStatus.SUBMITTED:
        raise ValidationError(_('Only submitted assignments can be approved for first approval.'))

    task = locked_assign.task
    if task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('Cannot approve a completed or cancelled task.'))

    # Move assignment to SECOND_APPROVAL
    locked_assign.assignment_status = TaskAssignment.AssignmentStatus.SECOND_APPROVAL
    locked_assign.save(update_fields=['assignment_status', 'updated_at'])
    assignment.assignment_status = locked_assign.assignment_status

    latest_sub = TaskSubmission.objects.filter(assignment=locked_assign).order_by('-version').first()
    if latest_sub:
        latest_sub.status = TaskSubmission.SubmissionStatus.FIRST_APPROVED
        latest_sub.save(update_fields=['status', 'updated_at'])

    approval = TaskApproval.objects.create(
        task=task,
        assignment=locked_assign,
        submission=latest_sub,
        stage=TaskApproval.Stage.FIRST_APPROVAL,
        decision=TaskApproval.Decision.APPROVED,
        actor=actor,
        actor_role_code='DEPARTMENT_HEAD' if actor.is_department_head else 'MANAGEMENT',
        reason=notes.strip(),
    )

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.FIRST_APPROVAL_APPROVED,
        new_value={
            'approval_id': str(approval.id),
            'approved_by': actor.display_name,
            'stage': 'FIRST_APPROVAL',
            'notes': notes.strip(),
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FIRST_APPROVAL_APPROVED,
        target_repr=f"{task.task_number}: first approved by {actor.display_name}",
        details={'assignment_id': str(locked_assign.id), 'approval_id': str(approval.id)},
        request=request,
    )

    # Notify Employee
    create_notification(
        recipient=locked_assign.user,
        notification_type=Notification.NotificationType.FIRST_APPROVAL_APPROVED,
        title=_('First Approval Granted'),
        message=_('{task_num} was approved by {head} and sent for second approval.').format(
            task_num=task.task_number,
            head=actor.display_name,
        ),
        task=task,
        link=f"/workflow/assignments/{locked_assign.id}/",
    )

    # Notify Rector & Responsible Vice Rector(s)
    from accounts.models import Role
    rector_role = Role.objects.filter(code=Role.Codes.RECTOR).first()
    rector_users = User.objects.filter(roles=rector_role, is_active=True) if rector_role else User.objects.none()
    for rec in rector_users:
        create_notification(
            recipient=rec,
            notification_type=Notification.NotificationType.FIRST_APPROVAL_APPROVED,
            title=_('Second Approval Required'),
            message=_('{head} approved {task_num} and sent it for second approval.').format(
                head=actor.display_name,
                task_num=task.task_number,
            ),
            task=task,
            link=f"/workflow/management/second-approval/{locked_assign.id}/",
        )

    if task.responsible_department:
        for resp in task.responsible_department.vice_rector_responsibilities.filter(is_active=True).select_related('vice_rector'):
            if resp.vice_rector and resp.vice_rector.is_active:
                create_notification(
                    recipient=resp.vice_rector,
                    notification_type=Notification.NotificationType.FIRST_APPROVAL_APPROVED,
                    title=_('Second Approval Required'),
                    message=_('{head} approved {task_num} and sent it for second approval.').format(
                        head=actor.display_name,
                        task_num=task.task_number,
                    ),
                    task=task,
                    link=f"/workflow/management/second-approval/{locked_assign.id}/",
                )

    return approval


@transaction.atomic
def first_reject_assignment(
    actor: User, assignment: TaskAssignment, reason: str, request=None
):
    """
    Department Head rejects submitted task.
    assignment status: SUBMITTED → REJECTED
    Reason is strictly required.
    """
    from tasks.permissions import can_first_reject_assignment
    if not can_first_reject_assignment(actor, assignment):
        raise ValidationError(_('You do not have permission to reject this assignment.'))

    reason = (reason or '').strip()
    if not reason:
        raise ValidationError(_('Rejection reason is required.'))

    locked_assign = TaskAssignment.objects.select_for_update().select_related('task', 'user').get(pk=assignment.pk)
    if locked_assign.assignment_status != TaskAssignment.AssignmentStatus.SUBMITTED:
        raise ValidationError(_('Only submitted assignments can be rejected at first approval.'))

    task = locked_assign.task
    if task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('Cannot reject a completed or cancelled task.'))

    locked_assign.assignment_status = TaskAssignment.AssignmentStatus.REJECTED
    locked_assign.save(update_fields=['assignment_status', 'updated_at'])
    assignment.assignment_status = locked_assign.assignment_status

    latest_sub = TaskSubmission.objects.filter(assignment=locked_assign).order_by('-version').first()
    if latest_sub:
        latest_sub.status = TaskSubmission.SubmissionStatus.FIRST_REJECTED
        latest_sub.save(update_fields=['status', 'updated_at'])

    approval = TaskApproval.objects.create(
        task=task,
        assignment=locked_assign,
        submission=latest_sub,
        stage=TaskApproval.Stage.FIRST_APPROVAL,
        decision=TaskApproval.Decision.REJECTED,
        actor=actor,
        actor_role_code='DEPARTMENT_HEAD' if actor.is_department_head else 'MANAGEMENT',
        reason=reason,
    )

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.FIRST_APPROVAL_REJECTED,
        new_value={
            'approval_id': str(approval.id),
            'rejected_by': actor.display_name,
            'reason': reason,
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FIRST_APPROVAL_REJECTED,
        target_repr=f"{task.task_number}: first rejected by {actor.display_name}",
        details={'assignment_id': str(locked_assign.id), 'reason': reason},
        request=request,
    )

    # Notify Employee
    create_notification(
        recipient=locked_assign.user,
        notification_type=Notification.NotificationType.FIRST_APPROVAL_REJECTED,
        title=_('Task Submission Rejected'),
        message=_('{task_num} was rejected during first approval by {head}. Reason: {reason}').format(
            task_num=task.task_number,
            head=actor.display_name,
            reason=reason,
        ),
        task=task,
        link=f"/workflow/assignments/{locked_assign.id}/",
    )

    return approval


@transaction.atomic
def final_approve_assignment(
    actor: User, assignment: TaskAssignment, notes: str = '', request=None
):
    """
    Rector / Responsible Vice Rector grants final approval.
    assignment status: SECOND_APPROVAL → APPROVED (progress=100)
    task status: IN_PROGRESS / ASSIGNED → COMPLETED (progress=100, completed_at=now)
    Creates TaskApproval(Stage=FINAL_APPROVAL, Decision=APPROVED).
    """
    from tasks.permissions import can_final_approve_assignment
    if not can_final_approve_assignment(actor, assignment):
        raise ValidationError(_('You do not have permission to grant final approval on this task.'))

    locked_assign = TaskAssignment.objects.select_for_update().select_related('task', 'user').get(pk=assignment.pk)
    if locked_assign.assignment_status not in (
        TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
        TaskAssignment.AssignmentStatus.SUBMITTED,
    ):
        raise ValidationError(_('This assignment is not awaiting second/final approval.'))

    task = locked_assign.task
    if task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('This task is already completed or closed.'))

    now = timezone.now()

    # Finalize assignment and parent task
    locked_assign.assignment_status = TaskAssignment.AssignmentStatus.APPROVED
    locked_assign.progress = 100
    locked_assign.save(update_fields=['assignment_status', 'progress', 'updated_at'])
    assignment.assignment_status = locked_assign.assignment_status
    assignment.progress = locked_assign.progress

    task.status = Task.Status.COMPLETED
    task.progress = 100
    task.completed_at = now
    task.save(update_fields=['status', 'progress', 'completed_at', 'updated_at'])

    latest_sub = TaskSubmission.objects.filter(assignment=locked_assign).order_by('-version').first()
    if latest_sub:
        latest_sub.status = TaskSubmission.SubmissionStatus.FINAL_APPROVED
        latest_sub.save(update_fields=['status', 'updated_at'])

    approval = TaskApproval.objects.create(
        task=task,
        assignment=locked_assign,
        submission=latest_sub,
        stage=TaskApproval.Stage.FINAL_APPROVAL,
        decision=TaskApproval.Decision.APPROVED,
        actor=actor,
        actor_role_code='RECTOR' if actor.is_rector else 'VICE_RECTOR',
        reason=notes.strip(),
    )

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.FINAL_APPROVAL,
        new_value={
            'approval_id': str(approval.id),
            'approved_by': actor.display_name,
            'completed_at': now.isoformat(),
            'notes': notes.strip(),
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FINAL_APPROVAL,
        target_repr=f"{task.task_number}: final approved (completed) by {actor.display_name}",
        details={'assignment_id': str(locked_assign.id), 'approval_id': str(approval.id)},
        request=request,
    )

    # Notify Employee
    create_notification(
        recipient=locked_assign.user,
        notification_type=Notification.NotificationType.FINAL_APPROVED,
        title=_('Task Successfully Completed'),
        message=_('{task_num} has been successfully completed and finally approved by {manager}.').format(
            task_num=task.task_number,
            manager=actor.display_name,
        ),
        task=task,
        link=f"/workflow/completed/",
    )

    # Notify Department Head
    if task.responsible_department:
        dept_head = task.responsible_department.head or User.objects.filter(
            department=task.responsible_department,
            roles__code='DEPARTMENT_HEAD',
            is_active=True,
        ).first()
        if dept_head:
            create_notification(
                recipient=dept_head,
                notification_type=Notification.NotificationType.FINAL_APPROVED,
                title=_('Task Successfully Completed'),
                message=_('{task_num} has been finally approved by {manager}.').format(
                    task_num=task.task_number,
                    manager=actor.display_name,
                ),
                task=task,
                link=f"/workflow/completed/",
            )

    # Automatic targeted KPI recalculation for completed assignment
    try:
        from kpi.calculation import recalculate_employee_period_kpis
        from kpi.models import KPIPeriod
        for p in KPIPeriod.objects.filter(is_active=True, status=KPIPeriod.Status.OPEN):
            recalculate_employee_period_kpis(locked_assign.user, p, actor=actor)
    except Exception:
        pass

    return approval


@transaction.atomic
def final_reject_assignment(
    actor: User, assignment: TaskAssignment, reason: str, request=None
):
    """
    Rector / Responsible Vice Rector rejects task at second approval.
    assignment status → REJECTED
    Reason is strictly required.
    """
    from tasks.permissions import can_second_reject_assignment
    if not can_second_reject_assignment(actor, assignment):
        raise ValidationError(_('You do not have permission to reject this assignment.'))

    reason = (reason or '').strip()
    if not reason:
        raise ValidationError(_('Rejection reason is required.'))

    locked_assign = TaskAssignment.objects.select_for_update().select_related('task', 'user').get(pk=assignment.pk)
    task = locked_assign.task

    if task.signatures.filter(status='SIGNED').exists():
        raise ValidationError(_('Cannot reject an officially signed task.'))

    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('Cannot reject a cancelled or archived task.'))

    is_awaiting_approval = locked_assign.assignment_status in (
        TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
        TaskAssignment.AssignmentStatus.SUBMITTED,
        TaskAssignment.AssignmentStatus.APPROVED,
    )
    is_awaiting_signature = (task.status == Task.Status.COMPLETED and not task.signatures.filter(status='SIGNED').exists())

    if not (is_awaiting_approval or is_awaiting_signature):
        raise ValidationError(_('This assignment is not awaiting second approval or signing.'))

    # If the task was previously set to COMPLETED (prior to electronic signature),
    # revert it back to IN_PROGRESS upon executive rejection.
    if task.status == Task.Status.COMPLETED:
        task.status = Task.Status.IN_PROGRESS
        task.completed_at = None
        task.progress = min(task.progress, 90)
        task.save(update_fields=['status', 'completed_at', 'progress', 'updated_at'])

    locked_assign.assignment_status = TaskAssignment.AssignmentStatus.REJECTED
    locked_assign.save(update_fields=['assignment_status', 'updated_at'])
    assignment.assignment_status = locked_assign.assignment_status

    latest_sub = TaskSubmission.objects.filter(assignment=locked_assign).order_by('-version').first()
    if latest_sub:
        latest_sub.status = TaskSubmission.SubmissionStatus.FINAL_REJECTED
        latest_sub.save(update_fields=['status', 'updated_at'])

    approval = TaskApproval.objects.create(
        task=task,
        assignment=locked_assign,
        submission=latest_sub,
        stage=TaskApproval.Stage.SECOND_APPROVAL,
        decision=TaskApproval.Decision.REJECTED,
        actor=actor,
        actor_role_code='RECTOR' if (actor.is_rector or actor.is_superuser) else 'VICE_RECTOR',
        reason=reason,
    )

    TaskHistory.objects.create(
        task=task,
        actor=actor,
        event_type=TaskHistory.EventType.SECOND_APPROVAL_REJECTED,
        new_value={
            'approval_id': str(approval.id),
            'rejected_by': actor.display_name,
            'reason': reason,
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.SECOND_APPROVAL_REJECTED,
        target_repr=f"{task.task_number}: second rejected by {actor.display_name}",
        details={'assignment_id': str(locked_assign.id), 'reason': reason},
        request=request,
    )

    # Notify Employee
    create_notification(
        recipient=locked_assign.user,
        notification_type=Notification.NotificationType.FINAL_REJECTED,
        title=_('Task Submission Rejected (Second Approval)'),
        message=_('{task_num} was rejected during second approval by {manager}. Reason: {reason}').format(
            task_num=task.task_number,
            manager=actor.display_name,
            reason=reason,
        ),
        task=task,
        link=f"/workflow/assignments/{locked_assign.id}/",
    )

    # Notify Department Head
    if task.responsible_department:
        dept_head = task.responsible_department.head or User.objects.filter(
            department=task.responsible_department,
            roles__code='DEPARTMENT_HEAD',
            is_active=True,
        ).first()
        if dept_head:
            create_notification(
                recipient=dept_head,
                notification_type=Notification.NotificationType.FINAL_REJECTED,
                title=_('Task Rejected during Second Approval'),
                message=_('{task_num} was rejected during second approval by {manager}. Reason: {reason}').format(
                    task_num=task.task_number,
                    manager=actor.display_name,
                    reason=reason,
                ),
                task=task,
                link=f"/workflow/rejected/",
            )

    return approval


@transaction.atomic
def extend_task_deadline(
    actor: User, task: Task, new_deadline, reason: str, request=None
):
    """
    Rector / Responsible Vice Rector extends official task deadline.
    new_deadline must be strictly > current task.deadline.
    Reason is strictly required.
    """
    from tasks.permissions import can_extend_task_deadline
    if not can_extend_task_deadline(actor, task):
        raise ValidationError(_('You do not have permission to extend the deadline of this task.'))

    reason = (reason or '').strip()
    if not reason:
        raise ValidationError(_('Deadline extension reason is required.'))

    locked_task = Task.objects.select_for_update().get(pk=task.pk)
    if locked_task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        raise ValidationError(_('Cannot extend deadline on a completed or cancelled task.'))

    if not new_deadline:
        raise ValidationError(_('A new deadline date is required.'))

    if locked_task.deadline and new_deadline <= locked_task.deadline:
        raise ValidationError(_('The new deadline must be later than the current deadline.'))

    old_deadline = locked_task.deadline
    locked_task.deadline = new_deadline
    locked_task.save(update_fields=['deadline', 'updated_at'])

    extension = TaskDeadlineExtension.objects.create(
        task=locked_task,
        old_deadline=old_deadline,
        new_deadline=new_deadline,
        extended_by=actor,
        reason=reason,
    )

    TaskHistory.objects.create(
        task=locked_task,
        actor=actor,
        event_type=TaskHistory.EventType.DEADLINE_EXTENDED,
        old_value={'deadline': old_deadline.isoformat() if old_deadline else None},
        new_value={
            'deadline': new_deadline.isoformat(),
            'extended_by': actor.display_name,
            'reason': reason,
        },
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.DEADLINE_EXTENDED,
        target_repr=f"{locked_task.task_number}: deadline extended to {new_deadline}",
        details={
            'extension_id': str(extension.id),
            'old_deadline': str(old_deadline),
            'new_deadline': str(new_deadline),
            'reason': reason,
        },
        request=request,
    )

    # Notify Assignees
    for assign in locked_task.assignments.select_related('user').all():
        create_notification(
            recipient=assign.user,
            notification_type=Notification.NotificationType.DEADLINE_EXTENDED,
            title=_('Task Deadline Extended'),
            message=_('Deadline for {task_num} was extended to {new_date} by {manager}. Reason: {reason}').format(
                task_num=locked_task.task_number,
                new_date=new_deadline,
                manager=actor.display_name,
                reason=reason,
            ),
            task=locked_task,
            link=f"/workflow/assignments/{assign.id}/",
        )

    # Notify Department Head
    if locked_task.responsible_department and locked_task.responsible_department.head:
        create_notification(
            recipient=locked_task.responsible_department.head,
            notification_type=Notification.NotificationType.DEADLINE_EXTENDED,
            title=_('Task Deadline Extended'),
            message=_('Deadline for {task_num} was extended to {new_date} by {manager}. Reason: {reason}').format(
                task_num=locked_task.task_number,
                new_date=new_deadline,
                manager=actor.display_name,
                reason=reason,
            ),
            task=locked_task,
            link=f"/workflow/dept/tasks/",
        )

    return extension

