from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from tasks.models import Task, TaskAssignment


def can_view_task(user: User, task: Task) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.can_act_as_rector:
        return True
    if user.is_vice_rector:
        scoped_depts = user.get_scoped_departments()
        if task.responsible_department_id and scoped_depts.filter(id=task.responsible_department_id).exists():
            return True
        if task.secondary_departments.filter(id__in=scoped_depts.values_list('id', flat=True)).exists():
            return True
        if task.assignments.filter(user__department__in=scoped_depts).exists():
            return True
        return task.creator_id == user.id
    if user.is_department_head and user.department_id:
        if task.responsible_department_id == user.department_id:
            return True
        if task.secondary_departments.filter(id=user.department_id).exists():
            return True
        if task.assignments.filter(user__department_id=user.department_id).exists():
            return True
        return task.creator_id == user.id
    if user.is_employee:
        return task.assignments.filter(user=user).exists()
    return False


def can_create_task(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.can_act_as_rector or user.is_vice_rector or user.is_department_head


# Statuses that indicate a task has started execution — editing is blocked at this point
_TASK_STARTED_STATUSES = (
    Task.Status.IN_PROGRESS,
    Task.Status.COMPLETED,
    Task.Status.CANCELLED,
    Task.Status.ARCHIVED,
)


def can_edit_task(user: User, task: Task) -> bool:
    """
    Only the task creator (or superadmin) may edit a task.
    Editing is blocked once the task has been picked up (IN_PROGRESS or beyond).
    """
    if not user.is_authenticated:
        return False
    # Superadmin has no restrictions
    if user.is_superuser:
        return True
    # Block editing once any assignee has started work or the task is terminal
    if task.status in _TASK_STARTED_STATUSES:
        return False
    # Also block if an assignment is actively in progress / submitted
    if is_task_in_submission_or_approval(task):
        return False
    # Only the original creator may edit
    return task.creator_id is not None and task.creator_id == user.id


def can_delete_task(user: User, task: Task) -> bool:
    """
    Only the task creator (or superadmin) may delete a task.
    Deletion is blocked once work has begun (status IN_PROGRESS or beyond,
    or any assignment is in the submission/approval pipeline).
    """
    if not user.is_authenticated:
        return False
    # Superadmin has no restrictions
    if user.is_superuser:
        return True
    # Block deletion once any assignee has started work or the task is terminal
    if task.status in _TASK_STARTED_STATUSES:
        return False
    # Also block if any assignment is in progress, submitted, or under review
    if task.assignments.filter(
        assignment_status__in=[
            TaskAssignment.AssignmentStatus.IN_PROGRESS,
            TaskAssignment.AssignmentStatus.SUBMITTED,
            TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
            TaskAssignment.AssignmentStatus.APPROVED,
        ]
    ).exists():
        return False
    # Only the original creator may delete
    return task.creator_id is not None and task.creator_id == user.id


def can_cancel_task(user: User, task: Task) -> bool:
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED, Task.Status.COMPLETED):
        return False
    if user.is_superuser or user.can_act_as_rector:
        return True
    if user.is_vice_rector:
        if not task.responsible_department_id:
            return task.creator_id == user.id
        return user.get_scoped_departments().filter(id=task.responsible_department_id).exists()
    return False


def can_archive_task(user: User, task: Task) -> bool:
    if not user.is_authenticated:
        return False
    if task.status not in (Task.Status.COMPLETED, Task.Status.CANCELLED):
        return False
    if user.is_superuser or user.can_act_as_rector:
        return True
    if user.is_vice_rector:
        if not task.responsible_department_id:
            return task.creator_id == user.id
        return user.get_scoped_departments().filter(id=task.responsible_department_id).exists()
    return False


def is_task_in_submission_or_approval(task: Task) -> bool:
    """
    Check if a task is currently in submission / approval review phase
    (i.e. an employee has submitted their work and it is in "Submitted Tasks"
    awaiting first or second approval), or the task is completed/cancelled/archived.
    """
    if task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return True

    # Any assignment currently submitted or in second approval stage
    has_submitted_assignment = task.assignments.filter(
        assignment_status__in=[
            TaskAssignment.AssignmentStatus.SUBMITTED,
            TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
        ]
    ).exists()
    if has_submitted_assignment:
        return True

    # Any submission pending first or second approval
    from tasks.models import TaskSubmission
    return task.submissions.filter(
        status__in=[
            TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL,
            TaskSubmission.SubmissionStatus.FIRST_APPROVED,
        ]
    ).exists()


def can_assign_task(user: User, task: Task) -> bool:
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED, Task.Status.COMPLETED):
        return False

    # When a task is in "Submitted Tasks" (under review/approval),
    # Vice Rector, Department Head, and Employee cannot manage assignees.
    if is_task_in_submission_or_approval(task):
        if not (user.is_superuser or user.can_act_as_rector):
            return False

    if user.is_superuser or user.can_act_as_rector:
        return True
    if user.is_vice_rector:
        scoped_depts = user.get_scoped_departments()
        if task.responsible_department_id and scoped_depts.filter(id=task.responsible_department_id).exists():
            return True
        if task.secondary_departments.filter(id__in=scoped_depts.values_list('id', flat=True)).exists():
            return True
        return task.creator_id == user.id
    if user.is_department_head and user.department_id:
        if task.responsible_department_id == user.department_id:
            return True
        if task.secondary_departments.filter(id=user.department_id).exists():
            return True
        return task.creator_id == user.id
    return False


def can_unassign_user(actor: User, task: Task, assignment: TaskAssignment) -> bool:
    """
    Check if actor is allowed to unassign assignment from task.

    Strict Rules:
    1. An assigned employee can NEVER unassign themselves ("biriktrilgan xodim hech qachon o'zini o'zi assigned dan chiqarmasin").
    2. When a task has been submitted / is in review (in Submitted Tasks), Vice Rector, Department Head, and Employee cannot unassign anyone.
    3. An assignment that has already been submitted or approved cannot be unassigned by Vice Rector or Department Head.
    4. Role & Assigner Hierarchy:
       - Only the assigner role (or higher authority) can unassign/replace the employee.
       - If assigned by RECTOR (or superuser): only RECTOR or superuser can unassign.
       - If assigned by VICE_RECTOR: only VICE_RECTOR (within departmental scope) or RECTOR (or superuser) can unassign. Department heads CANNOT.
       - If assigned by DEPARTMENT_HEAD: DEPARTMENT_HEAD (of the responsible department), VICE_RECTOR, or RECTOR can unassign.
       - If assigned_by is None: fallback to can_assign_task(actor, task) (and actor != assignment.user).
    """
    if not actor.is_authenticated:
        return False

    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED, Task.Status.COMPLETED):
        return False

    # 1. An assigned user can NEVER unassign themselves
    if assignment.user_id == actor.id:
        return False

    # 2. If task is in submitted/review status or assignment is submitted/approved, non-rector/superusers cannot unassign
    if is_task_in_submission_or_approval(task) or assignment.assignment_status in (
        TaskAssignment.AssignmentStatus.SUBMITTED,
        TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
        TaskAssignment.AssignmentStatus.APPROVED,
    ):
        if not (actor.is_superuser or actor.is_rector):
            return False

    # Superuser and Rector have top-level authority over any assignment
    if actor.is_superuser or actor.is_rector:
        return True

    assigned_by = assignment.assigned_by

    # 3. If assigned by Rector (or superuser): only Rector / superuser can unassign
    if assigned_by and (assigned_by.is_superuser or assigned_by.is_rector):
        return False

    # 4. If actor is Vice Rector:
    if actor.is_vice_rector:
        if not task.responsible_department_id:
            return False
        return actor.get_scoped_departments().filter(id=task.responsible_department_id).exists()

    # 5. If assigned by Vice Rector: Department Head cannot unassign
    if assigned_by and assigned_by.is_vice_rector:
        return False

    # 6. If actor is Department Head:
    if actor.is_department_head and actor.department_id:
        return task.responsible_department_id == actor.department_id

    return False



def can_manage_subtasks(user: User, task: Task) -> bool:
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_vice_rector:
        return user.get_scoped_departments().filter(id=task.responsible_department_id).exists()
    if user.is_department_head:
        return task.responsible_department_id == user.department_id
    if user.is_employee:
        return task.assignments.filter(user=user).exists()
    return False


def can_manage_dependencies(user: User, task: Task) -> bool:
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_vice_rector:
        return user.get_scoped_departments().filter(id=task.responsible_department_id).exists()
    if user.is_department_head:
        return task.responsible_department_id == user.department_id
    return False


def can_manage_task_types(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector


def can_manage_templates(user: User) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_rector or user.is_vice_rector



# ---------------------------------------------------------------------------
# CBV Mixins
# ---------------------------------------------------------------------------

class TaskAccessMixin(AccessMixin):
    def get_task(self):
        task_id = self.kwargs.get('pk') or self.kwargs.get('task_id')
        task = get_object_or_404(Task, pk=task_id)
        if not can_view_task(self.request.user, task):
            raise PermissionDenied(_('You do not have permission to view this task.'))
        return task

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_task()
        return super().dispatch(request, *args, **kwargs)


class TaskEditMixin(AccessMixin):
    def get_task(self):
        task_id = self.kwargs.get('pk') or self.kwargs.get('task_id')
        task = get_object_or_404(Task, pk=task_id)
        if not can_edit_task(self.request.user, task):
            raise PermissionDenied(_('You do not have permission to edit this task.'))
        return task

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_task()
        return super().dispatch(request, *args, **kwargs)


class TaskDeleteMixin(AccessMixin):
    def get_task(self):
        task_id = self.kwargs.get('pk') or self.kwargs.get('task_id')
        task = get_object_or_404(Task, pk=task_id)
        if not can_delete_task(self.request.user, task):
            raise PermissionDenied(_('You do not have permission to delete this task.'))
        return task

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_task()
        return super().dispatch(request, *args, **kwargs)


class TaskAssignMixin(AccessMixin):
    def get_task(self):
        task_id = self.kwargs.get('pk') or self.kwargs.get('task_id')
        task = get_object_or_404(Task, pk=task_id)
        if not can_assign_task(self.request.user, task):
            raise PermissionDenied(_('You do not have permission to assign employees to this task.'))
        return task

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_task()
        return super().dispatch(request, *args, **kwargs)


class TaskCancelMixin(AccessMixin):
    def get_task(self):
        task_id = self.kwargs.get('pk') or self.kwargs.get('task_id')
        task = get_object_or_404(Task, pk=task_id)
        if not can_cancel_task(self.request.user, task):
            raise PermissionDenied(_('You do not have permission to cancel this task.'))
        return task

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_task()
        return super().dispatch(request, *args, **kwargs)


class TaskArchiveMixin(AccessMixin):
    def get_task(self):
        task_id = self.kwargs.get('pk') or self.kwargs.get('task_id')
        task = get_object_or_404(Task, pk=task_id)
        if not can_archive_task(self.request.user, task):
            raise PermissionDenied(_('You do not have permission to archive this task.'))
        return task

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.get_task()
        return super().dispatch(request, *args, **kwargs)


class TaskCreateRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_create_task(request.user):
            raise PermissionDenied(_('You do not have permission to create tasks.'))
        return super().dispatch(request, *args, **kwargs)


# ===========================================================================
# PHASE 4 — Employee Workflow Permissions
# ===========================================================================

def can_accept_assignment(user: User, assignment) -> bool:
    """Only the assigned employee can accept, and only if ASSIGNED and task is active."""
    if not user.is_authenticated:
        return False
    if assignment.user_id != user.id:
        return False
    if assignment.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    from tasks.models import TaskAssignment
    return assignment.assignment_status == TaskAssignment.AssignmentStatus.ASSIGNED


def can_update_assignment_progress(user: User, assignment) -> bool:
    """Only the assigned employee can update progress, and only if IN_PROGRESS and task is active."""
    if not user.is_authenticated:
        return False
    if assignment.user_id != user.id:
        return False
    if assignment.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    from tasks.models import TaskAssignment
    return assignment.assignment_status == TaskAssignment.AssignmentStatus.IN_PROGRESS


def can_add_task_note(user: User, task: Task, assignment=None) -> bool:
    """Assigned employee or department head of the responsible department can add notes."""
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    if user.is_superuser or user.is_rector or user.is_vice_rector:
        return True
    if user.is_department_head and user.department_id:
        return task.responsible_department_id == user.department_id
    if user.is_employee:
        return task.assignments.filter(user=user).exists()
    return False


def can_start_rework(user: User, assignment) -> bool:
    """
    Assigned employee or superuser can resume/start rework on an assignment that was rejected.
    Task must be active (not completed/cancelled/archived).
    """
    if not user.is_authenticated:
        return False
    if assignment.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    from tasks.models import TaskAssignment
    if assignment.assignment_status != TaskAssignment.AssignmentStatus.REJECTED:
        return False
    return assignment.user_id == user.id or user.is_superuser


def can_submit_assignment(user: User, assignment) -> bool:
    """Only the assigned employee can submit, if IN_PROGRESS or REJECTED, and task is active."""
    if not user.is_authenticated:
        return False
    if assignment.user_id != user.id and not user.is_superuser:
        return False
    if assignment.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    from tasks.models import TaskAssignment
    return assignment.assignment_status in (
        TaskAssignment.AssignmentStatus.IN_PROGRESS,
        TaskAssignment.AssignmentStatus.REJECTED,
    )


def can_view_submission(user: User, submission) -> bool:
    """Assigned employee, dept head of responsible dept, or rector/vice rector can view."""
    if not user.is_authenticated:
        return False
    if user.is_rector:
        return True
    if user.is_vice_rector:
        task = submission.task
        if not task.responsible_department_id:
            return True
        return user.get_scoped_departments().filter(id=task.responsible_department_id).exists()
    if user.is_department_head and user.department_id:
        return submission.task.responsible_department_id == user.department_id
    # Employee can view their own submission
    return submission.submitted_by_id == user.id or submission.assignment.user_id == user.id


def can_assign_employees_to_task(user: User, task: Task) -> bool:
    """Department Head can assign employees only to tasks in their own department."""
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED, Task.Status.COMPLETED):
        return False

    # When task is submitted / in approval, Vice Rector and Department Head cannot assign employees
    if is_task_in_submission_or_approval(task):
        if not (user.is_superuser or user.can_act_as_rector):
            return False

    if user.is_superuser or user.can_act_as_rector:
        return True
    if user.is_vice_rector:
        scoped_depts = user.get_scoped_departments()
        if task.responsible_department_id and scoped_depts.filter(id=task.responsible_department_id).exists():
            return True
        if task.secondary_departments.filter(id__in=scoped_depts.values_list('id', flat=True)).exists():
            return True
        return task.creator_id == user.id
    if user.is_department_head and user.department_id:
        if task.responsible_department_id == user.department_id:
            return True
        if task.secondary_departments.filter(id=user.department_id).exists():
            return True
        return task.creator_id == user.id
    return False


# ===========================================================================
# PHASE 5 — Management Approval, Rejection & Deadline Extension Permissions
# ===========================================================================

def can_first_approve_assignment(user: User, assignment) -> bool:
    """Department Head of task or assignee's department, or superadmin (technical bypass), can first-approve."""
    if not user.is_authenticated:
        return False
    from tasks.models import TaskAssignment
    if assignment.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    if assignment.assignment_status != TaskAssignment.AssignmentStatus.SUBMITTED:
        return False
    if user.is_superuser:
        return True
    if user.is_department_head and user.department_id:
        if assignment.task.responsible_department_id == user.department_id:
            return True
        if assignment.task.secondary_departments.filter(id=user.department_id).exists():
            return True
        if assignment.user.department_id == user.department_id:
            return True
        return False
    return False


def can_first_reject_assignment(user: User, assignment) -> bool:
    """Same permission policy as first approval (Department Head only)."""
    return can_first_approve_assignment(user, assignment)


def can_second_approve_assignment(user: User, assignment) -> bool:
    """Only Rector (university-wide) or responsible Vice Rector can second/final approve."""
    if not user.is_authenticated:
        return False
    from tasks.models import TaskAssignment
    task = assignment.task
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    if task.signatures.filter(status='SIGNED').exists():
        return False

    if user.is_superuser or user.can_act_as_rector:
        return bool(
            task.status == Task.Status.COMPLETED
            or assignment.assignment_status in (
                TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                TaskAssignment.AssignmentStatus.SUBMITTED,
            )
        )

    if user.is_vice_rector:
        if task.status == Task.Status.COMPLETED:
            return False
        if assignment.assignment_status not in (
            TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
            TaskAssignment.AssignmentStatus.SUBMITTED,
        ):
            return False
        dept_id = task.responsible_department_id
        scoped_depts = user.get_scoped_departments()
        if dept_id and scoped_depts.filter(id=dept_id).exists():
            return True
        if assignment.user.department_id and scoped_depts.filter(id=assignment.user.department_id).exists():
            return True
        return False

    return False


def can_second_reject_assignment(user: User, assignment) -> bool:
    """
    Rector (university-wide), Superadmin, or responsible Vice Rector can reject at second approval / signing stage.
    If the document has come for signing, Rector must be able to reject it if deliverables are unsatisfactory.
    """
    if not user.is_authenticated:
        return False
    from tasks.models import TaskAssignment
    task = assignment.task
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    if task.signatures.filter(status='SIGNED').exists():
        return False

    if user.is_superuser or user.can_act_as_rector:
        return bool(
            task.status == Task.Status.COMPLETED
            or assignment.assignment_status in (
                TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                TaskAssignment.AssignmentStatus.SUBMITTED,
                TaskAssignment.AssignmentStatus.APPROVED,
            )
        )

    if user.is_vice_rector:
        if task.status == Task.Status.COMPLETED:
            return False
        if assignment.assignment_status not in (
            TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
            TaskAssignment.AssignmentStatus.SUBMITTED,
        ):
            return False
        dept_id = task.responsible_department_id
        scoped_depts = user.get_scoped_departments()
        if dept_id and scoped_depts.filter(id=dept_id).exists():
            return True
        if assignment.user.department_id and scoped_depts.filter(id=assignment.user.department_id).exists():
            return True
        return False

    return False


def can_final_approve_assignment(user: User, assignment) -> bool:
    """Alias for second/final approval."""
    return can_second_approve_assignment(user, assignment)


def can_extend_task_deadline(user: User, task: Task) -> bool:
    """Only Rector (university-wide) or responsible Vice Rector can extend official task deadline."""
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False
    if user.is_superuser or user.is_rector:
        return True
    if user.is_vice_rector:
        dept_id = task.responsible_department_id
        return bool(dept_id and user.get_scoped_departments().filter(id=dept_id).exists())
    return False

