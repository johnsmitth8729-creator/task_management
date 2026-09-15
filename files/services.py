from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from core.models import AuditLog, Notification, create_notification, log_audit
from files.models import TaskFile, TaskFolder, TaskReport
from files.permissions import (
    can_create_report,
    can_delete_file,
    can_edit_report,
    can_manage_folders,
    can_upload_task_file,
)
from files.validators import (
    calculate_file_checksum,
    detect_content_type,
    get_file_extension,
    sanitize_filename,
    validate_file_extension,
    validate_file_size,
)
from tasks.models import Task, TaskAssignment, TaskSubmission


# ---------------------------------------------------------------------------
# Folder Services
# ---------------------------------------------------------------------------

@transaction.atomic
def create_task_folder(
    actor: User,
    task: Task,
    name: str,
    parent_folder: TaskFolder | None = None,
    request=None,
) -> TaskFolder:
    """Creates a logical folder for organizing files within a task."""
    if not can_manage_folders(actor, task):
        raise ValidationError(_('You do not have permission to create folders for this task.'))

    name = (name or '').strip()
    if not name:
        raise ValidationError(_('Folder name cannot be empty.'))
    if len(name) > 150:
        raise ValidationError(_('Folder name is too long (maximum 150 characters).'))

    if TaskFolder.objects.filter(task=task, parent_folder=parent_folder, name=name, is_active=True).exists():
        raise ValidationError(_('A folder with this name already exists in this location.'))

    folder = TaskFolder.objects.create(
        task=task,
        name=name,
        parent_folder=parent_folder,
        created_by=actor,
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FOLDER_CREATED,
        target_repr=f"Folder '{name}' created on {task.task_number}",
        details={'folder_id': str(folder.id), 'task_id': str(task.id)},
        request=request,
    )

    return folder


@transaction.atomic
def rename_task_folder(
    actor: User,
    folder: TaskFolder,
    new_name: str,
    request=None,
) -> TaskFolder:
    """Renames a logical folder."""
    if not can_manage_folders(actor, folder.task):
        raise ValidationError(_('You do not have permission to modify this folder.'))

    new_name = (new_name or '').strip()
    if not new_name:
        raise ValidationError(_('Folder name cannot be empty.'))

    old_name = folder.name
    if TaskFolder.objects.filter(
        task=folder.task,
        parent_folder=folder.parent_folder,
        name=new_name,
        is_active=True,
    ).exclude(id=folder.id).exists():
        raise ValidationError(_('A folder with this name already exists in this location.'))

    folder.name = new_name
    folder.save(update_fields=['name', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FOLDER_RENAMED,
        target_repr=f"Folder renamed from '{old_name}' to '{new_name}' on {folder.task.task_number}",
        details={'folder_id': str(folder.id), 'old_name': old_name, 'new_name': new_name},
        request=request,
    )

    return folder


@transaction.atomic
def delete_task_folder(
    actor: User,
    folder: TaskFolder,
    request=None,
) -> None:
    """Soft deletes a logical folder and moves files to parent folder or root."""
    if not can_manage_folders(actor, folder.task):
        raise ValidationError(_('You do not have permission to delete this folder.'))

    folder.files.filter(is_active=True).update(folder=folder.parent_folder)
    folder.subfolders.filter(is_active=True).update(parent_folder=folder.parent_folder)

    folder.is_active = False
    folder.save(update_fields=['is_active', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FOLDER_DELETED,
        target_repr=f"Folder '{folder.name}' deleted on {folder.task.task_number}",
        details={'folder_id': str(folder.id)},
        request=request,
    )


# ---------------------------------------------------------------------------
# File Services
# ---------------------------------------------------------------------------

@transaction.atomic
def upload_task_file(
    actor: User,
    task: Task,
    file_obj,
    description: str = '',
    folder: TaskFolder | None = None,
    assignment: TaskAssignment | None = None,
    submission: TaskSubmission | None = None,
    category: str = TaskFile.Category.WORK_EVIDENCE,
    request=None,
) -> TaskFile:
    """
    Validates, sanitizes, checksums, and securely stores an uploaded task file.
    """
    if not can_upload_task_file(actor, task, assignment=assignment):
        raise ValidationError(_('You do not have permission to upload files to this task.'))

    if not file_obj:
        raise ValidationError(_('Please select a file to upload.'))

    raw_filename = getattr(file_obj, 'name', '') or 'unnamed_file'
    ext = validate_file_extension(raw_filename)
    is_video = ext in ['mp4', 'webm']
    file_size = validate_file_size(file_obj, is_video=is_video)

    clean_orig_name = sanitize_filename(raw_filename)
    checksum = calculate_file_checksum(file_obj)
    content_type = detect_content_type(clean_orig_name)

    task_file = TaskFile(
        task=task,
        assignment=assignment,
        submission=submission,
        folder=folder,
        uploaded_by=actor,
        file=file_obj,
        original_filename=clean_orig_name,
        stored_filename='',  # populates on save from FileField
        file_extension=ext,
        content_type=content_type,
        file_size=file_size,
        checksum=checksum,
        category=category,
        version=submission.version if submission else 1,
        description=description.strip(),
        is_active=True,
    )
    task_file.save()

    task_file.stored_filename = task_file.file.name
    task_file.save(update_fields=['stored_filename'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FILE_UPLOADED,
        target_repr=f"Uploaded '{clean_orig_name}' ({task_file.file_size_display}) to {task.task_number}",
        details={
            'file_id': str(task_file.id),
            'filename': clean_orig_name,
            'size': file_size,
            'checksum': checksum,
        },
        request=request,
    )

    # Notify Department Head if employee uploads evidence
    if actor.is_employee and task.responsible_department and task.responsible_department.head:
        create_notification(
            recipient=task.responsible_department.head,
            notification_type=Notification.NotificationType.FILE_UPLOADED,
            title=_('New Work Evidence Uploaded'),
            message=_('{employee} uploaded evidence file "{file}" to {task_num}.').format(
                employee=actor.display_name,
                file=clean_orig_name,
                task_num=task.task_number,
            ),
            task=task,
            link=f"/workflow/dept/tasks/{task.id}/",
        )

    return task_file


@transaction.atomic
def soft_delete_task_file(
    actor: User,
    task_file: TaskFile,
    request=None,
) -> None:
    """Soft deletes a file."""
    if not can_delete_file(actor, task_file):
        raise ValidationError(_('You do not have permission to delete this file.'))

    task_file.is_active = False
    task_file.deleted_at = timezone.now()
    task_file.deleted_by = actor
    task_file.save(update_fields=['is_active', 'deleted_at', 'deleted_by', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FILE_DELETED,
        target_repr=f"Deleted file '{task_file.original_filename}' on {task_file.task.task_number}",
        details={'file_id': str(task_file.id), 'filename': task_file.original_filename},
        request=request,
    )


@transaction.atomic
def move_task_file(
    actor: User,
    task_file: TaskFile,
    target_folder: TaskFolder | None,
    request=None,
) -> TaskFile:
    """Moves a file into a folder (or to root if target_folder is None)."""
    if not can_upload_task_file(actor, task_file.task):
        raise ValidationError(_('You do not have permission to organize files on this task.'))

    if target_folder and target_folder.task_id != task_file.task_id:
        raise ValidationError(_('Cannot move file to a folder from a different task.'))

    old_folder_name = task_file.folder.name if task_file.folder else 'Root'
    new_folder_name = target_folder.name if target_folder else 'Root'

    task_file.folder = target_folder
    task_file.save(update_fields=['folder', 'updated_at'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.FILE_MOVED,
        target_repr=f"Moved '{task_file.original_filename}' from '{old_folder_name}' to '{new_folder_name}'",
        details={'file_id': str(task_file.id), 'folder_id': str(target_folder.id) if target_folder else None},
        request=request,
    )

    return task_file


# ---------------------------------------------------------------------------
# Report Services
# ---------------------------------------------------------------------------

@transaction.atomic
def create_task_report(
    actor: User,
    task: Task,
    title: str,
    summary: str,
    completed_work: str,
    results: str,
    reporting_period: str = '',
    problems: str = '',
    recommendations: str = '',
    conclusion: str = '',
    assignment: TaskAssignment | None = None,
    status: str = TaskReport.Status.DRAFT,
    request=None,
) -> TaskReport:
    """Creates a structured work report."""
    if not can_create_report(actor, task):
        raise ValidationError(_('You do not have permission to create a report for this task.'))

    title = (title or '').strip()
    if not title:
        raise ValidationError(_('Report title cannot be empty.'))
    summary = (summary or '').strip()
    if not summary:
        raise ValidationError(_('Executive summary cannot be empty.'))
    completed_work = (completed_work or '').strip()
    if not completed_work:
        raise ValidationError(_('Completed work description cannot be empty.'))
    results = (results or '').strip()
    if not results:
        raise ValidationError(_('Results and deliverables cannot be empty.'))

    report = TaskReport.objects.create(
        task=task,
        assignment=assignment,
        author=actor,
        title=title,
        reporting_period=reporting_period.strip(),
        summary=summary,
        completed_work=completed_work,
        results=results,
        problems=problems.strip(),
        recommendations=recommendations.strip(),
        conclusion=conclusion.strip(),
        status=status,
    )

    log_audit(
        actor=actor,
        action=AuditLog.Actions.REPORT_CREATED,
        target_repr=f"Report '{title}' created on {task.task_number}",
        details={'report_id': str(report.id), 'status': status},
        request=request,
    )

    # Notify Department Head if submitted
    if status == TaskReport.Status.SUBMITTED and task.responsible_department and task.responsible_department.head:
        create_notification(
            recipient=task.responsible_department.head,
            notification_type=Notification.NotificationType.REPORT_SUBMITTED,
            title=_('New Task Report Submitted'),
            message=_('{author} submitted report "{title}" for {task_num}.').format(
                author=actor.display_name,
                title=title,
                task_num=task.task_number,
            ),
            task=task,
            link=f"/files/reports/{report.id}/",
        )

    return report


@transaction.atomic
def update_task_report(
    actor: User,
    report: TaskReport,
    title: str | None = None,
    summary: str | None = None,
    completed_work: str | None = None,
    results: str | None = None,
    reporting_period: str | None = None,
    problems: str | None = None,
    recommendations: str | None = None,
    conclusion: str | None = None,
    status: str | None = None,
    request=None,
) -> TaskReport:
    """Updates a structured work report."""
    if not can_edit_report(actor, report):
        raise ValidationError(_('You do not have permission to edit this report.'))

    update_fields = ['updated_at']

    if title is not None:
        title = title.strip()
        if not title:
            raise ValidationError(_('Report title cannot be empty.'))
        report.title = title
        update_fields.append('title')

    if summary is not None:
        summary = summary.strip()
        if not summary:
            raise ValidationError(_('Executive summary cannot be empty.'))
        report.summary = summary
        update_fields.append('summary')

    if completed_work is not None:
        completed_work = completed_work.strip()
        if not completed_work:
            raise ValidationError(_('Completed work description cannot be empty.'))
        report.completed_work = completed_work
        update_fields.append('completed_work')

    if results is not None:
        results = results.strip()
        if not results:
            raise ValidationError(_('Results and deliverables cannot be empty.'))
        report.results = results
        update_fields.append('results')

    if reporting_period is not None:
        report.reporting_period = reporting_period.strip()
        update_fields.append('reporting_period')

    if problems is not None:
        report.problems = problems.strip()
        update_fields.append('problems')

    if recommendations is not None:
        report.recommendations = recommendations.strip()
        update_fields.append('recommendations')

    if conclusion is not None:
        report.conclusion = conclusion.strip()
        update_fields.append('conclusion')

    if status is not None and status in TaskReport.Status.values:
        report.status = status
        update_fields.append('status')

    report.save(update_fields=update_fields)

    log_audit(
        actor=actor,
        action=AuditLog.Actions.REPORT_UPDATED,
        target_repr=f"Report '{report.title}' updated on {report.task.task_number}",
        details={'report_id': str(report.id), 'status': report.status},
        request=request,
    )

    return report
