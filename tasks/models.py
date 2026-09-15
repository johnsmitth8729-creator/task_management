import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# TaskType
# ---------------------------------------------------------------------------

class TaskType(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=200)
    code = models.CharField(_('code'), max_length=50, unique=True)
    description = models.TextField(_('description'), blank=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['name']
        verbose_name = _('task type')
        verbose_name_plural = _('task types')

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class Task(TimeStampedModel):

    class Priority(models.TextChoices):
        LOW = 'LOW', _('Low')
        MEDIUM = 'MEDIUM', _('Medium')
        HIGH = 'HIGH', _('High')
        URGENT = 'URGENT', _('Urgent')

    class Complexity(models.TextChoices):
        SIMPLE = 'SIMPLE', _('Simple')
        MEDIUM = 'MEDIUM', _('Medium')
        COMPLEX = 'COMPLEX', _('Complex')
        CRITICAL = 'CRITICAL', _('Critical')

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        CREATED = 'CREATED', _('Created')
        ASSIGNED = 'ASSIGNED', _('Assigned')
        IN_PROGRESS = 'IN_PROGRESS', _('In Progress')
        COMPLETED = 'COMPLETED', _('Completed')
        CANCELLED = 'CANCELLED', _('Cancelled')
        ARCHIVED = 'ARCHIVED', _('Archived')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_number = models.CharField(
        _('task number'),
        max_length=20,
        unique=True,
        blank=True,  # set automatically on save
        db_index=True,
    )
    title = models.CharField(_('title'), max_length=500)
    description = models.TextField(_('description'), blank=True)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('creator'),
        on_delete=models.SET_NULL,
        related_name='created_tasks',
        null=True,
        blank=True,
    )
    responsible_department = models.ForeignKey(
        'organization.Department',
        verbose_name=_('responsible department'),
        on_delete=models.SET_NULL,
        related_name='tasks',
        null=True,
        blank=True,
    )
    secondary_departments = models.ManyToManyField(
        'organization.Department',
        verbose_name=_('co-responsible / secondary departments'),
        related_name='co_responsible_tasks',
        blank=True,
    )
    task_type = models.ForeignKey(
        TaskType,
        verbose_name=_('task type'),
        on_delete=models.SET_NULL,
        related_name='tasks',
        null=True,
        blank=True,
    )
    priority = models.CharField(
        _('priority'),
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )
    complexity = models.CharField(
        _('complexity'),
        max_length=10,
        choices=Complexity.choices,
        default=Complexity.SIMPLE,
        db_index=True,
    )
    status = models.CharField(
        _('status'),
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    progress = models.IntegerField(
        _('progress (%)'),
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    start_date = models.DateField(_('start date'), null=True, blank=True)
    deadline = models.DateField(_('deadline'), null=True, blank=True, db_index=True)

    # Completion/Cancellation/Archive
    completed_at = models.DateTimeField(_('completed at'), null=True, blank=True)
    cancelled_at = models.DateTimeField(_('cancelled at'), null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('cancelled by'),
        on_delete=models.SET_NULL,
        related_name='cancelled_tasks',
        null=True,
        blank=True,
    )
    cancellation_reason = models.TextField(_('cancellation reason'), blank=True)
    archived_at = models.DateTimeField(_('archived at'), null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['priority']),
            models.Index(fields=['complexity']),
            models.Index(fields=['deadline']),
            models.Index(fields=['creator']),
            models.Index(fields=['responsible_department', 'status']),
            models.Index(fields=['status', 'deadline']),
            models.Index(fields=['creator', 'status']),
        ]
        verbose_name = _('task')
        verbose_name_plural = _('tasks')

    def __str__(self):
        return f"{self.task_number}: {self.title}"

    def save(self, *args, **kwargs):
        if not self.task_number:
            self.task_number = self._generate_task_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_task_number() -> str:
        from django.db import connection
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT nextval('task_number_seq')")
                n = cursor.fetchone()[0]
            return f"TM-{n:06d}"
        except Exception:
            # Fallback if sequence not yet ready or non-postgres
            count = Task.objects.count() + 1
            return f"TM-{count:06d}"

    @property
    def is_overdue(self) -> bool:
        """Derived property — does not change status. Per architecture spec."""
        if not self.deadline:
            return False
        if self.status in (self.Status.COMPLETED, self.Status.CANCELLED, self.Status.ARCHIVED):
            return False
        return timezone.now().date() > self.deadline

    @property
    def days_until_deadline(self):
        if not self.deadline:
            return None
        return (self.deadline - timezone.now().date()).days

    @property
    def is_active(self) -> bool:
        return self.status not in (self.Status.CANCELLED, self.Status.ARCHIVED)

    @property
    def primary_assignee(self):
        assignment = self.assignments.filter(is_primary=True).select_related('user').first()
        return assignment.user if assignment else None

    @property
    def assignees(self):
        return [a.user for a in self.assignments.select_related('user').all()]


# ---------------------------------------------------------------------------
# TaskAssignment — Phase 4 extended with assignment workflow fields
# ---------------------------------------------------------------------------

class TaskAssignment(TimeStampedModel):

    class AssignmentStatus(models.TextChoices):
        ASSIGNED = 'ASSIGNED', _('Assigned')
        IN_PROGRESS = 'IN_PROGRESS', _('In Progress')
        SUBMITTED = 'SUBMITTED', _('Submitted for Approval')
        SECOND_APPROVAL = 'SECOND_APPROVAL', _('Pending Second Approval')
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='assignments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('assigned user'),
        on_delete=models.CASCADE,
        related_name='task_assignments',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('assigned by'),
        on_delete=models.SET_NULL,
        related_name='task_assignments_made',
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField(_('assigned at'), auto_now_add=True)
    is_primary = models.BooleanField(_('primary assignee'), default=False)

    # Phase 4 — Assignment workflow fields
    assignment_status = models.CharField(
        _('assignment status'),
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ASSIGNED,
        db_index=True,
    )
    accepted_at = models.DateTimeField(_('accepted at'), null=True, blank=True)
    progress = models.IntegerField(
        _('assignment progress (%)'),
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    class Meta:
        ordering = ['-is_primary', 'assigned_at']
        indexes = [
            models.Index(fields=['task', 'user']),
            models.Index(fields=['user']),
            models.Index(fields=['assignment_status']),
            models.Index(fields=['user', 'assignment_status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['task'],
                condition=models.Q(is_primary=True),
                name='unique_primary_assignment_per_task',
            ),
            models.UniqueConstraint(
                fields=['task', 'user'],
                name='unique_task_user_assignment',
            ),
        ]
        verbose_name = _('task assignment')
        verbose_name_plural = _('task assignments')

    def __str__(self):
        primary = ' (Primary)' if self.is_primary else ''
        return f"{self.task.task_number} → {self.user.display_name}{primary} [{self.assignment_status}]"


# ---------------------------------------------------------------------------
# SubTask
# ---------------------------------------------------------------------------

class SubTask(TimeStampedModel):

    class Status(models.TextChoices):
        TODO = 'TODO', _('To Do')
        IN_PROGRESS = 'IN_PROGRESS', _('In Progress')
        DONE = 'DONE', _('Done')
        CANCELLED = 'CANCELLED', _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_task = models.ForeignKey(
        Task,
        verbose_name=_('parent task'),
        on_delete=models.CASCADE,
        related_name='subtasks',
    )
    title = models.CharField(_('title'), max_length=500)
    description = models.TextField(_('description'), blank=True)
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
    )
    progress = models.IntegerField(
        _('progress (%)'),
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('assignee'),
        on_delete=models.SET_NULL,
        related_name='subtask_assignments',
        null=True,
        blank=True,
    )
    deadline = models.DateField(_('deadline'), null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = _('subtask')
        verbose_name_plural = _('subtasks')

    def __str__(self):
        return f"{self.parent_task.task_number} — {self.title}"


# ---------------------------------------------------------------------------
# TaskDependency
# ---------------------------------------------------------------------------

class TaskDependency(models.Model):

    class DependencyType(models.TextChoices):
        FINISH_TO_START = 'FINISH_TO_START', _('Finish to Start')
        START_TO_START = 'START_TO_START', _('Start to Start')
        FINISH_TO_FINISH = 'FINISH_TO_FINISH', _('Finish to Finish')
        START_TO_FINISH = 'START_TO_FINISH', _('Start to Finish')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='dependencies',
    )
    depends_on = models.ForeignKey(
        Task,
        verbose_name=_('depends on'),
        on_delete=models.CASCADE,
        related_name='dependents',
    )
    dependency_type = models.CharField(
        _('dependency type'),
        max_length=20,
        choices=DependencyType.choices,
        default=DependencyType.FINISH_TO_START,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'depends_on'],
                name='unique_task_dependency',
            ),
        ]
        verbose_name = _('task dependency')
        verbose_name_plural = _('task dependencies')

    def __str__(self):
        return f"{self.task.task_number} depends on {self.depends_on.task_number}"


# ---------------------------------------------------------------------------
# TaskTemplate
# ---------------------------------------------------------------------------

class TaskTemplate(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=300)
    description = models.TextField(_('description'), blank=True)
    task_type = models.ForeignKey(
        TaskType,
        verbose_name=_('task type'),
        on_delete=models.SET_NULL,
        related_name='templates',
        null=True,
        blank=True,
    )
    default_priority = models.CharField(
        _('default priority'),
        max_length=10,
        choices=Task.Priority.choices,
        default=Task.Priority.MEDIUM,
    )
    default_complexity = models.CharField(
        _('default complexity'),
        max_length=10,
        choices=Task.Complexity.choices,
        default=Task.Complexity.SIMPLE,
    )
    default_duration_days = models.PositiveIntegerField(
        _('default duration (days)'),
        null=True,
        blank=True,
        help_text=_('Number of days from creation to deadline.'),
    )
    is_active = models.BooleanField(_('active'), default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='task_templates',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = _('task template')
        verbose_name_plural = _('task templates')

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# RecurringTask  (config-only; no Celery automation in Phase 3)
# ---------------------------------------------------------------------------

class RecurringTask(TimeStampedModel):

    class Frequency(models.TextChoices):
        DAILY = 'DAILY', _('Daily')
        WEEKLY = 'WEEKLY', _('Weekly')
        MONTHLY = 'MONTHLY', _('Monthly')
        YEARLY = 'YEARLY', _('Yearly')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(_('title'), max_length=500)
    template = models.ForeignKey(
        TaskTemplate,
        verbose_name=_('template'),
        on_delete=models.SET_NULL,
        related_name='recurring_tasks',
        null=True,
        blank=True,
    )
    responsible_department = models.ForeignKey(
        'organization.Department',
        verbose_name=_('responsible department'),
        on_delete=models.SET_NULL,
        related_name='recurring_tasks',
        null=True,
        blank=True,
    )
    frequency = models.CharField(
        _('frequency'),
        max_length=10,
        choices=Frequency.choices,
        default=Frequency.MONTHLY,
    )
    start_date = models.DateField(_('start date'))
    end_date = models.DateField(_('end date'), null=True, blank=True)
    next_run_at = models.DateField(_('next run at'), null=True, blank=True)
    is_active = models.BooleanField(_('active'), default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created by'),
        on_delete=models.SET_NULL,
        related_name='recurring_tasks',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['title']
        verbose_name = _('recurring task')
        verbose_name_plural = _('recurring tasks')

    def __str__(self):
        return f"{self.title} ({self.get_frequency_display()})"


# ---------------------------------------------------------------------------
# TaskHistory  (user-facing timeline) — Phase 4 extended event types
# ---------------------------------------------------------------------------

class TaskHistory(models.Model):

    class EventType(models.TextChoices):
        # Phase 3
        TASK_CREATED = 'TASK_CREATED', _('Task Created')
        TASK_UPDATED = 'TASK_UPDATED', _('Task Updated')
        STATUS_CHANGED = 'STATUS_CHANGED', _('Status Changed')
        PRIORITY_CHANGED = 'PRIORITY_CHANGED', _('Priority Changed')
        COMPLEXITY_CHANGED = 'COMPLEXITY_CHANGED', _('Complexity Changed')
        DEADLINE_CHANGED = 'DEADLINE_CHANGED', _('Deadline Changed')
        DEPARTMENT_CHANGED = 'DEPARTMENT_CHANGED', _('Department Changed')
        TASK_ASSIGNED = 'TASK_ASSIGNED', _('Task Assigned')
        TASK_UNASSIGNED = 'TASK_UNASSIGNED', _('User Unassigned')
        TASK_CANCELLED = 'TASK_CANCELLED', _('Task Cancelled')
        TASK_ARCHIVED = 'TASK_ARCHIVED', _('Task Archived')
        SUBTASK_CREATED = 'SUBTASK_CREATED', _('Subtask Created')
        DEPENDENCY_ADDED = 'DEPENDENCY_ADDED', _('Dependency Added')
        DEPENDENCY_REMOVED = 'DEPENDENCY_REMOVED', _('Dependency Removed')
        PROGRESS_UPDATED = 'PROGRESS_UPDATED', _('Progress Updated')
        # Phase 4 — Employee workflow events
        TASK_ACCEPTED = 'TASK_ACCEPTED', _('Task Accepted')
        ASSIGNMENT_PROGRESS_UPDATED = 'ASSIGNMENT_PROGRESS_UPDATED', _('Assignment Progress Updated')
        TASK_NOTE_CREATED = 'TASK_NOTE_CREATED', _('Work Note Added')
        TASK_SUBMISSION_CREATED = 'TASK_SUBMISSION_CREATED', _('Submitted for First Approval')
        TASK_REWORK_STARTED = 'TASK_REWORK_STARTED', _('Task Rework Started')
        # Phase 5 — Management approval & rejection events
        FIRST_APPROVAL_APPROVED = 'FIRST_APPROVAL_APPROVED', _('First Approval Granted')
        FIRST_APPROVAL_REJECTED = 'FIRST_APPROVAL_REJECTED', _('First Approval Rejected')
        SECOND_APPROVAL_APPROVED = 'SECOND_APPROVAL_APPROVED', _('Second Approval Granted')
        SECOND_APPROVAL_REJECTED = 'SECOND_APPROVAL_REJECTED', _('Second Approval Rejected')
        FINAL_APPROVAL = 'FINAL_APPROVAL', _('Final Approval Granted (Task Completed)')
        DEADLINE_EXTENDED = 'DEADLINE_EXTENDED', _('Task Deadline Extended')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='history',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('actor'),
        on_delete=models.SET_NULL,
        related_name='task_history_entries',
        null=True,
        blank=True,
    )
    event_type = models.CharField(_('event type'), max_length=30, choices=EventType.choices)
    old_value = models.JSONField(_('old value'), default=dict, blank=True)
    new_value = models.JSONField(_('new value'), default=dict, blank=True)
    created_at = models.DateTimeField(_('timestamp'), auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', 'created_at']),
            models.Index(fields=['event_type']),
        ]
        verbose_name = _('task history')
        verbose_name_plural = _('task history')

    def __str__(self):
        actor_name = self.actor.display_name if self.actor else 'System'
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_name}: {self.get_event_type_display()} on {self.task.task_number}"


# ---------------------------------------------------------------------------
# TaskNote — Phase 4: Employee work notes
# ---------------------------------------------------------------------------

class TaskNote(TimeStampedModel):

    class Visibility(models.TextChoices):
        EMPLOYEE = 'EMPLOYEE', _('All (Assignees & Management)')
        DEPARTMENT_HEAD = 'DEPARTMENT_HEAD', _('Department Head & Management')
        MANAGEMENT = 'MANAGEMENT', _('Management Only (Rector / Vice Rector)')
        INTERNAL = 'INTERNAL', _('Internal (Author Only)')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='notes',
    )
    assignment = models.ForeignKey(
        TaskAssignment,
        verbose_name=_('assignment'),
        on_delete=models.CASCADE,
        related_name='notes',
        null=True,
        blank=True,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('author'),
        on_delete=models.SET_NULL,
        related_name='task_notes',
        null=True,
        blank=True,
    )
    content = models.TextField(_('content'))
    visibility = models.CharField(
        _('visibility'),
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.EMPLOYEE,
        db_index=True,
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', 'created_at']),
            models.Index(fields=['assignment']),
            models.Index(fields=['author']),
            models.Index(fields=['visibility']),
        ]
        verbose_name = _('task note')
        verbose_name_plural = _('task notes')

    def __str__(self):
        author_name = self.author.display_name if self.author else 'Unknown'
        return f"Note by {author_name} on {self.task.task_number}"


# ---------------------------------------------------------------------------
# TaskSubmission — Phase 4: Employee submission for first approval
# ---------------------------------------------------------------------------

class TaskSubmission(TimeStampedModel):

    class SubmissionStatus(models.TextChoices):
        PENDING_FIRST_APPROVAL = 'PENDING_FIRST_APPROVAL', _('Pending First Approval')
        FIRST_APPROVED = 'FIRST_APPROVED', _('First Approved (Pending Second Approval)')
        FIRST_REJECTED = 'FIRST_REJECTED', _('First Rejected')
        FINAL_APPROVED = 'FINAL_APPROVED', _('Final Approved')
        FINAL_REJECTED = 'FINAL_REJECTED', _('Final Rejected')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='submissions',
    )
    assignment = models.ForeignKey(
        TaskAssignment,
        verbose_name=_('assignment'),
        on_delete=models.CASCADE,
        related_name='submissions',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('submitted by'),
        on_delete=models.SET_NULL,
        related_name='task_submissions',
        null=True,
        blank=True,
    )
    submission_text = models.TextField(_('submission text'))
    submitted_at = models.DateTimeField(_('submitted at'), default=timezone.now)
    version = models.PositiveIntegerField(_('version'), default=1)
    status = models.CharField(
        _('status'),
        max_length=30,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.PENDING_FIRST_APPROVAL,
    )

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['task', 'submitted_at']),
            models.Index(fields=['assignment', 'version']),
            models.Index(fields=['status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'version'],
                name='unique_submission_version_per_assignment',
            ),
        ]
        verbose_name = _('task submission')
        verbose_name_plural = _('task submissions')

    def __str__(self):
        return f"Submission v{self.version} by {self.submitted_by.display_name if self.submitted_by else '?'} for {self.task.task_number}"


# ---------------------------------------------------------------------------
# TaskDeadlineExtension — Phase 5: Official deadline extension history
# ---------------------------------------------------------------------------

class TaskDeadlineExtension(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='deadline_extensions',
    )
    old_deadline = models.DateField(_('old deadline'))
    new_deadline = models.DateField(_('new deadline'))
    extended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('extended by'),
        on_delete=models.SET_NULL,
        related_name='deadline_extensions_granted',
        null=True,
        blank=True,
    )
    reason = models.TextField(_('reason'))

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', '-created_at']),
        ]
        verbose_name = _('deadline extension')
        verbose_name_plural = _('deadline extensions')

    def __str__(self):
        return f"Deadline extension for {self.task.task_number}: {self.old_deadline} -> {self.new_deadline}"


# ---------------------------------------------------------------------------
# TaskApproval — Phase 5: Review & approval record model
# ---------------------------------------------------------------------------

class TaskApproval(TimeStampedModel):

    class Stage(models.TextChoices):
        FIRST_APPROVAL = 'FIRST_APPROVAL', _('First Approval (Department Head)')
        SECOND_APPROVAL = 'SECOND_APPROVAL', _('Second Approval (Management)')
        FINAL_APPROVAL = 'FINAL_APPROVAL', _('Final Approval')

    class Decision(models.TextChoices):
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        verbose_name=_('task'),
        on_delete=models.CASCADE,
        related_name='approvals',
    )
    assignment = models.ForeignKey(
        TaskAssignment,
        verbose_name=_('assignment'),
        on_delete=models.CASCADE,
        related_name='approvals',
        null=True,
        blank=True,
    )
    submission = models.ForeignKey(
        TaskSubmission,
        verbose_name=_('submission'),
        on_delete=models.CASCADE,
        related_name='approvals',
        null=True,
        blank=True,
    )
    stage = models.CharField(_('stage'), max_length=30, choices=Stage.choices)
    decision = models.CharField(_('decision'), max_length=20, choices=Decision.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('actor'),
        on_delete=models.SET_NULL,
        related_name='task_approvals_given',
        null=True,
        blank=True,
    )
    actor_role_code = models.CharField(_('actor role code'), max_length=50, blank=True)
    reason = models.TextField(_('reason / comments'), blank=True)
    metadata = models.JSONField(_('metadata'), default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task', '-created_at']),
            models.Index(fields=['assignment', 'stage']),
            models.Index(fields=['decision']),
        ]
        verbose_name = _('task approval record')
        verbose_name_plural = _('task approval records')

    def __str__(self):
        actor_name = self.actor.display_name if self.actor else 'System'
        return f"{self.get_stage_display()} -> {self.get_decision_display()} by {actor_name} on {self.task.task_number}"

