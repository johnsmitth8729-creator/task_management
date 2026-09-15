import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from organization.models import Department


class RequestCategory(models.Model):
    """
    High-level category for university services and operational requests.
    """
    class CategoryCode(models.TextChoices):
        ACADEMIC = 'ACADEMIC', _('Academic & Curriculum')
        ADMINISTRATIVE = 'ADMINISTRATIVE', _('Administrative & Governance')
        HR_LEAVE = 'HR_LEAVE', _('Human Resources & Leave Requests')
        FINANCIAL = 'FINANCIAL', _('Financial, Grants & Procurement')
        FACILITIES = 'FACILITIES', _('Facilities, Logistics & Campus')
        IT_SERVICES = 'IT_SERVICES', _('IT & Digital Infrastructure')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('category name'), max_length=150)
    code = models.CharField(_('category code'), max_length=40, choices=CategoryCode.choices, unique=True)
    description = models.TextField(_('description'), blank=True)
    icon_class = models.CharField(_('bootstrap icon class'), max_length=50, default='bi-folder2-open')
    display_order = models.PositiveIntegerField(_('display order'), default=10)
    is_active = models.BooleanField(_('is active'), default=True)

    class Meta:
        verbose_name = _('request category')
        verbose_name_plural = _('request categories')
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


class RequestType(models.Model):
    """
    Specific request workflow definition (e.g. Annual Leave, Equipment Purchase, Course Addition).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        RequestCategory,
        verbose_name=_('category'),
        on_delete=models.CASCADE,
        related_name='request_types'
    )
    name = models.CharField(_('request type name'), max_length=180)
    code = models.CharField(_('request type code'), max_length=50, unique=True)
    description = models.TextField(_('description'), blank=True)
    
    # Workflow Stage Configurations
    requires_dept_head_approval = models.BooleanField(_('requires Department Head approval'), default=True)
    requires_dean_or_vr_approval = models.BooleanField(_('requires Dean / Vice Rector approval'), default=True)
    requires_hr_approval = models.BooleanField(_('requires HR Manager approval'), default=False)
    requires_finance_approval = models.BooleanField(_('requires Finance approval'), default=False)
    requires_rector_approval = models.BooleanField(_('requires Rector final approval'), default=False)
    
    sla_resolution_hours = models.PositiveIntegerField(_('standard resolution SLA (hours)'), default=72)
    form_schema = models.JSONField(
        _('dynamic form fields schema'),
        default=list,
        blank=True,
        help_text=_('JSON schema defining required custom inputs (e.g. leave dates, equipment specs, budgets).')
    )
    is_active = models.BooleanField(_('is active'), default=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('request type')
        verbose_name_plural = _('request types')
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class UniversityRequest(models.Model):
    """
    An official university service request or application submitted by staff/faculty.
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        SUBMITTED = 'SUBMITTED', _('Submitted / In Review')
        IN_REVIEW = 'IN_REVIEW', _('Under Multi-Tier Review')
        APPROVED = 'APPROVED', _('Fully Approved')
        REJECTED = 'REJECTED', _('Rejected')
        CANCELLED = 'CANCELLED', _('Cancelled by Requester')
        COMPLETED = 'COMPLETED', _('Fulfilled & Completed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_number = models.CharField(
        _('request tracking number'),
        max_length=30,
        unique=True,
        blank=True,
        db_index=True
    )
    request_type = models.ForeignKey(
        RequestType,
        verbose_name=_('request type'),
        on_delete=models.PROTECT,
        related_name='requests'
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('requester'),
        on_delete=models.CASCADE,
        related_name='university_requests'
    )
    department = models.ForeignKey(
        Department,
        verbose_name=_('originating department'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='department_requests'
    )
    subject = models.CharField(_('request subject / title'), max_length=255)
    details_payload = models.JSONField(_('request form data payload'), default=dict, blank=True)
    status = models.CharField(
        _('status'),
        max_length=30,
        choices=Status.choices,
        default=Status.SUBMITTED,
        db_index=True
    )
    current_step_number = models.PositiveIntegerField(_('current approval step number'), default=1)
    is_urgent = models.BooleanField(_('marked as urgent'), default=False)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    resolved_at = models.DateTimeField(_('resolved / completed at'), null=True, blank=True)

    class Meta:
        verbose_name = _('university request')
        verbose_name_plural = _('university requests')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['requester', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.request_number:
            year = timezone.now().year
            unique_seq = uuid.uuid4().hex[:6].upper()
            self.request_number = f"REQ-{year}-{unique_seq}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.request_number} — {self.subject} [{self.get_status_display()}]"


class RequestApprovalStep(models.Model):
    """
    An individual approval milestone in the multi-tier request workflow.
    """
    class ApproverRole(models.TextChoices):
        DEPARTMENT_HEAD = 'DEPARTMENT_HEAD', _('Department Head')
        VICE_RECTOR = 'VICE_RECTOR', _('Supervising Vice Rector / Dean')
        HR_MANAGER = 'HR_MANAGER', _('HR Department')
        FINANCE_DIRECTOR = 'FINANCE_DIRECTOR', _('Finance & Accounting')
        RECTOR = 'RECTOR', _('University Rector')

    class StepStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending Decision')
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')
        SKIPPED = 'SKIPPED', _('Skipped')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        UniversityRequest,
        verbose_name=_('university request'),
        on_delete=models.CASCADE,
        related_name='approval_steps'
    )
    step_number = models.PositiveIntegerField(_('step order number'), default=1)
    approver_role = models.CharField(_('approver role'), max_length=40, choices=ApproverRole.choices)
    assigned_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('assigned specific approver'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_request_approvals'
    )
    status = models.CharField(_('decision status'), max_length=20, choices=StepStatus.choices, default=StepStatus.PENDING)
    comments = models.TextField(_('approver comments / justification'), blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('decided by user'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='decided_request_steps'
    )
    decided_at = models.DateTimeField(_('decided at'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('request approval step')
        verbose_name_plural = _('request approval steps')
        ordering = ['request', 'step_number']
        constraints = [
            models.UniqueConstraint(
                fields=['request', 'step_number'],
                name='unique_request_step_number'
            )
        ]

    def __str__(self):
        return f"{self.request.request_number} Step {self.step_number}: {self.get_approver_role_display()} [{self.get_status_display()}]"


class UniversityDocument(models.Model):
    """
    Official promulgated university documents, rector orders, regulations, and charters.
    """
    class DocumentType(models.TextChoices):
        ORDER_RECTOR = 'ORDER_RECTOR', _('Rector Order / Buyruq')
        REGULATION = 'REGULATION', _('University Regulation / Nizom')
        DECREE_MINISTRY = 'DECREE_MINISTRY', _('Ministry Decree / Qaror')
        PROTOCOL_SENATE = 'PROTOCOL_SENATE', _('Senate Protocol / Bayonnoma')
        MEMORANDUM = 'MEMORANDUM', _('Internal Memorandum / Xizmat xati')

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        IN_REVIEW = 'IN_REVIEW', _('Under Review')
        SIGNED_ENACTED = 'SIGNED_ENACTED', _('Signed & In Effect')
        ARCHIVED = 'ARCHIVED', _('Archived / Superseded')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doc_number = models.CharField(_('official document reference number'), max_length=80, unique=True, db_index=True)
    title = models.CharField(_('document title'), max_length=300)
    document_type = models.CharField(_('document type'), max_length=40, choices=DocumentType.choices)
    description = models.TextField(_('summary / description'), blank=True)
    file = models.FileField(_('official document file (PDF/Doc)'), upload_to='documents/official/')
    version = models.PositiveIntegerField(_('document version'), default=1)
    status = models.CharField(_('status'), max_length=30, choices=Status.choices, default=Status.SIGNED_ENACTED)
    department = models.ForeignKey(
        Department,
        verbose_name=_('issuing department'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_documents'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('created / registered by'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registered_university_documents'
    )
    effective_date = models.DateField(_('effective date'), default=timezone.now)
    expiry_date = models.DateField(_('expiry date'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('university document')
        verbose_name_plural = _('university documents')
        ordering = ['-effective_date', '-created_at']

    def __str__(self):
        return f"[{self.doc_number}] {self.title} ({self.get_document_type_display()})"


class DocumentVersion(models.Model):
    """
    Historical versions of university documents.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        UniversityDocument,
        verbose_name=_('document'),
        on_delete=models.CASCADE,
        related_name='versions'
    )
    version_number = models.PositiveIntegerField(_('version number'))
    file = models.FileField(_('version file'), upload_to='documents/versions/')
    changelog = models.TextField(_('change summary'), blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('uploaded by'),
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_document_versions'
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('document version')
        verbose_name_plural = _('document versions')
        ordering = ['-version_number']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'version_number'],
                name='unique_document_version_number'
            )
        ]

    def __str__(self):
        return f"{self.document.doc_number} v{self.version_number}"
