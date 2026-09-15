import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from files.validators import task_file_upload_to


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# TaskFolder — Logical folder structure per Task
# ---------------------------------------------------------------------------

class TaskFolder(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        'tasks.Task',
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='folders',
    )
    name = models.CharField(_('folder name'), max_length=150)
    parent_folder = models.ForeignKey(
        'self',
        verbose_name=_('parent folder'),
        on_delete=models.CASCADE,
        related_name='subfolders',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='created_task_folders',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['task', 'is_active']),
            models.Index(fields=['parent_folder']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'parent_folder', 'name'],
                condition=models.Q(is_active=True),
                name='unique_active_folder_per_parent',
            ),
        ]
        verbose_name = _('task folder')
        verbose_name_plural = _('task folders')

    def __str__(self):
        return f"{self.name} [{self.task.task_number}]"

    @property
    def file_count(self) -> int:
        return self.files.filter(is_active=True).count()


# ---------------------------------------------------------------------------
# TaskFile — Production Work Evidence & Documents
# ---------------------------------------------------------------------------

class TaskFile(TimeStampedModel):

    class Category(models.TextChoices):
        WORK_EVIDENCE = 'WORK_EVIDENCE', _('Work Evidence')
        REQUIREMENTS = 'REQUIREMENTS', _('Requirements & Specs')
        REPORT_ATTACHMENT = 'REPORT_ATTACHMENT', _('Report Attachment')
        APPROVAL_DOCUMENT = 'APPROVAL_DOCUMENT', _('Approval Document')
        FINAL_SUBMISSION = 'FINAL_SUBMISSION', _('Final Submission Document')
        GENERAL = 'GENERAL', _('General Document')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        'tasks.Task',
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='files',
    )
    assignment = models.ForeignKey(
        'tasks.TaskAssignment',
        verbose_name=_('assignment'),
        on_delete=models.SET_NULL,
        related_name='files',
        null=True,
        blank=True,
    )
    submission = models.ForeignKey(
        'tasks.TaskSubmission',
        verbose_name=_('submission'),
        on_delete=models.SET_NULL,
        related_name='files',
        null=True,
        blank=True,
    )
    folder = models.ForeignKey(
        TaskFolder,
        verbose_name=_('folder'),
        on_delete=models.SET_NULL,
        related_name='files',
        null=True,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('uploaded by'),
        on_delete=models.SET_NULL,
        related_name='uploaded_task_files',
        null=True,
        blank=True,
    )
    file = models.FileField(_('file'), upload_to=task_file_upload_to)
    original_filename = models.CharField(_('original filename'), max_length=255)
    stored_filename = models.CharField(_('stored filename'), max_length=255, blank=True)
    file_extension = models.CharField(_('extension'), max_length=20, db_index=True)
    content_type = models.CharField(_('MIME content type'), max_length=100, blank=True)
    file_size = models.BigIntegerField(_('file size (bytes)'), default=0)
    checksum = models.CharField(_('SHA-256 Checksum'), max_length=64, blank=True, db_index=True)
    category = models.CharField(
        _('category'),
        max_length=30,
        choices=Category.choices,
        default=Category.WORK_EVIDENCE,
        db_index=True,
    )
    version = models.PositiveIntegerField(_('version'), default=1)
    description = models.TextField(_('description'), blank=True)

    # Soft deletion
    is_active = models.BooleanField(_('active'), default=True, db_index=True)
    deleted_at = models.DateTimeField(_('deleted at'), null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('deleted by'),
        on_delete=models.SET_NULL,
        related_name='deleted_task_files',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', 'is_active']),
            models.Index(fields=['assignment', 'is_active']),
            models.Index(fields=['submission', 'is_active']),
            models.Index(fields=['folder', 'is_active']),
            models.Index(fields=['uploaded_by', 'is_active']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['file_extension']),
        ]
        verbose_name = _('task file')
        verbose_name_plural = _('task files')

    def __str__(self):
        return f"{self.original_filename} (v{self.version}) on {self.task.task_number}"

    @property
    def file_size_display(self) -> str:
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

    @property
    def is_image(self) -> bool:
        return self.file_extension in ['jpg', 'jpeg', 'png', 'webp', 'gif']

    @property
    def is_pdf(self) -> bool:
        return self.file_extension == 'pdf'

    @property
    def is_video(self) -> bool:
        return self.file_extension in ['mp4', 'webm']

    @property
    def is_document(self) -> bool:
        return self.file_extension in ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'csv', 'txt']

    @property
    def is_archive(self) -> bool:
        return self.file_extension in ['zip', 'rar']

    @property
    def icon_class(self) -> str:
        """Returns Bootstrap Icons class appropriate for file type."""
        ext = self.file_extension
        if self.is_image:
            return 'bi-file-earmark-image text-info'
        elif self.is_pdf:
            return 'bi-file-earmark-pdf text-danger'
        elif ext in ['doc', 'docx']:
            return 'bi-file-earmark-word text-primary'
        elif ext in ['xls', 'xlsx', 'csv']:
            return 'bi-file-earmark-excel text-success'
        elif ext in ['ppt', 'pptx']:
            return 'bi-file-earmark-ppt text-warning'
        elif self.is_video:
            return 'bi-file-earmark-play text-danger'
        elif self.is_archive:
            return 'bi-file-earmark-zip text-secondary'
        elif ext == 'txt':
            return 'bi-file-earmark-text text-muted'
        return 'bi-file-earmark text-muted'


# ---------------------------------------------------------------------------
# TaskReport — Structured Work Reports attached to tasks
# ---------------------------------------------------------------------------

class TaskReport(TimeStampedModel):

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        SUBMITTED = 'SUBMITTED', _('Submitted for Review')
        APPROVED = 'APPROVED', _('Approved by Leadership')
        REJECTED = 'REJECTED', _('Rejected')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        'tasks.Task',
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='reports',
    )
    assignment = models.ForeignKey(
        'tasks.TaskAssignment',
        verbose_name=_('assignment'),
        on_delete=models.SET_NULL,
        related_name='reports',
        null=True,
        blank=True,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('author'),
        on_delete=models.SET_NULL,
        related_name='authored_task_reports',
        null=True,
        blank=True,
    )
    title = models.CharField(_('report title'), max_length=300)
    reporting_period = models.CharField(_('reporting period / milestone'), max_length=150, blank=True)
    summary = models.TextField(_('executive summary'))
    completed_work = models.TextField(_('completed work details'))
    results = models.TextField(_('key results & deliverables'))
    problems = models.TextField(_('identified challenges & issues'), blank=True)
    recommendations = models.TextField(_('recommendations & next steps'), blank=True)
    conclusion = models.TextField(_('conclusion'), blank=True)
    status = models.CharField(
        _('status'),
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    version = models.PositiveIntegerField(_('version'), default=1)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', 'status']),
            models.Index(fields=['author', 'status']),
        ]
        verbose_name = _('task report')
        verbose_name_plural = _('task reports')

    def __str__(self):
        return f"{self.title} (v{self.version}) — {self.task.task_number}"
