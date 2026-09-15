from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from files.models import TaskFile, TaskFolder, TaskReport
from tasks.models import Task, TaskAssignment, TaskSubmission
from tasks.permissions import can_view_task


def can_view_task_files(user: User, task: Task) -> bool:
    """Checks if user has permission to view files attached to this task."""
    return can_view_task(user, task)


def can_upload_task_file(user: User, task: Task, assignment: TaskAssignment | None = None) -> bool:
    """
    Checks if user is authorized to upload work evidence/attachments to this task.
    Task must be active (not CANCELLED or ARCHIVED).
    """
    if not user.is_authenticated:
        return False
    if task.status in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False

    if user.is_rector:
        return True
    if user.is_vice_rector:
        if not task.responsible_department_id:
            return task.creator_id == user.id
        return user.get_scoped_departments().filter(id=task.responsible_department_id).exists()
    if user.is_department_head and user.department_id:
        return task.responsible_department_id == user.department_id
    if user.is_employee:
        # Employee can upload if assigned to the task
        return task.assignments.filter(
            user=user,
            assignment_status__in=[
                TaskAssignment.AssignmentStatus.ASSIGNED,
                TaskAssignment.AssignmentStatus.IN_PROGRESS,
                TaskAssignment.AssignmentStatus.REJECTED,
            ],
        ).exists()

    return False


def can_download_file(user: User, task_file: TaskFile) -> bool:
    """Checks if user is authorized to download or view a file."""
    if not user.is_authenticated:
        return False
    if not task_file.is_active:
        return False
    return can_view_task(user, task_file.task)


def can_delete_file(user: User, task_file: TaskFile) -> bool:
    """
    Checks if user is authorized to soft-delete a file.
    Historical evidence attached to approved submissions cannot be deleted.
    """
    if not user.is_authenticated:
        return False
    if not task_file.is_active:
        return False
    if task_file.task.status in (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return False

    # Prevent deleting files attached to approved submissions
    if task_file.submission and task_file.submission.status in (
        TaskSubmission.SubmissionStatus.FIRST_APPROVED,
        TaskSubmission.SubmissionStatus.FINAL_APPROVED,
    ):
        return False

    if user.is_superuser or user.is_rector:
        return True
    if task_file.uploaded_by_id == user.id:
        return True
    if user.is_department_head and user.department_id:
        return task_file.task.responsible_department_id == user.department_id

    return False


def can_manage_folders(user: User, task: Task) -> bool:
    """Checks if user can create or modify folders in a task."""
    return can_upload_task_file(user, task)


def can_create_report(user: User, task: Task) -> bool:
    """Checks if user can create a structured work report on the task."""
    return can_upload_task_file(user, task)


def can_view_report(user: User, report: TaskReport) -> bool:
    """Checks if user can view the report."""
    return can_view_task(user, report.task)


def can_edit_report(user: User, report: TaskReport) -> bool:
    """Only author or rector can edit a report while it is in DRAFT or REJECTED status."""
    if not user.is_authenticated:
        return False
    if report.status not in (TaskReport.Status.DRAFT, TaskReport.Status.REJECTED):
        return False
    if user.is_rector:
        return True
    return report.author_id == user.id


def can_delete_report(user: User, report: TaskReport) -> bool:
    """Only author or rector can delete a draft report."""
    if not user.is_authenticated:
        return False
    if report.status not in (TaskReport.Status.DRAFT, TaskReport.Status.REJECTED):
        return False
    if user.is_rector:
        return True
    return report.author_id == user.id
