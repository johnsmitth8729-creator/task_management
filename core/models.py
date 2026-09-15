import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditLog(models.Model):
    class Actions(models.TextChoices):
        USER_CREATED = 'USER_CREATED', _('User Created')
        USER_UPDATED = 'USER_UPDATED', _('User Updated')
        USER_ACTIVATED = 'USER_ACTIVATED', _('User Activated')
        USER_DEACTIVATED = 'USER_DEACTIVATED', _('User Deactivated')
        USER_DELETED = 'USER_DELETED', _('User Deleted')
        ROLE_CHANGED = 'ROLE_CHANGED', _('Role Changed')
        DEPARTMENT_CREATED = 'DEPARTMENT_CREATED', _('Department Created')
        DEPARTMENT_UPDATED = 'DEPARTMENT_UPDATED', _('Department Updated')
        DEPARTMENT_HEAD_ASSIGNED = 'DEPARTMENT_HEAD_ASSIGNED', _('Department Head Assigned')
        DEPARTMENT_HEAD_CHANGED = 'DEPARTMENT_HEAD_CHANGED', _('Department Head Changed')
        VICE_RECTOR_RESPONSIBILITY_ASSIGNED = (
            'VICE_RECTOR_RESPONSIBILITY_ASSIGNED',
            _('Vice Rector Responsibility Assigned'),
        )
        VICE_RECTOR_RESPONSIBILITY_REMOVED = (
            'VICE_RECTOR_RESPONSIBILITY_REMOVED',
            _('Vice Rector Responsibility Removed'),
        )
        POSITION_CREATED = 'POSITION_CREATED', _('Position Created')
        POSITION_UPDATED = 'POSITION_UPDATED', _('Position Updated')
        # Phase 3 — Task Engine
        TASK_CREATED = 'TASK_CREATED', _('Task Created')
        TASK_UPDATED = 'TASK_UPDATED', _('Task Updated')
        TASK_STATUS_CHANGED = 'TASK_STATUS_CHANGED', _('Task Status Changed')
        TASK_CANCELLED = 'TASK_CANCELLED', _('Task Cancelled')
        TASK_ARCHIVED = 'TASK_ARCHIVED', _('Task Archived')
        TASK_ASSIGNED = 'TASK_ASSIGNED', _('Task Assigned')
        TASK_UNASSIGNED = 'TASK_UNASSIGNED', _('Task Unassigned')
        TASK_DEADLINE_CHANGED = 'TASK_DEADLINE_CHANGED', _('Task Deadline Changed')
        TASK_DEPARTMENT_CHANGED = 'TASK_DEPARTMENT_CHANGED', _('Task Department Changed')
        SUBTASK_CREATED = 'SUBTASK_CREATED', _('Subtask Created')
        SUBTASK_UPDATED = 'SUBTASK_UPDATED', _('Subtask Updated')
        SUBTASK_DELETED = 'SUBTASK_DELETED', _('Subtask Deleted')
        DEPENDENCY_CREATED = 'DEPENDENCY_CREATED', _('Task Dependency Created')
        DEPENDENCY_REMOVED = 'DEPENDENCY_REMOVED', _('Task Dependency Removed')
        TASK_TYPE_CREATED = 'TASK_TYPE_CREATED', _('Task Type Created')
        TASK_TYPE_UPDATED = 'TASK_TYPE_UPDATED', _('Task Type Updated')
        # Phase 4 — Employee workflow
        ASSIGNMENT_ACCEPTED = 'ASSIGNMENT_ACCEPTED', _('Assignment Accepted')
        ASSIGNMENT_PROGRESS_UPDATED = 'ASSIGNMENT_PROGRESS_UPDATED', _('Assignment Progress Updated')
        NOTE_CREATED = 'NOTE_CREATED', _('Work Note Created')
        ASSIGNMENT_SUBMITTED = 'ASSIGNMENT_SUBMITTED', _('Assignment Submitted for Approval')
        TASK_REWORK_STARTED = 'TASK_REWORK_STARTED', _('Task Rework Started')
        # Phase 5 — Management Approval & Rejection Workflow
        FIRST_APPROVAL_APPROVED = 'FIRST_APPROVAL_APPROVED', _('First Approval Granted')
        FIRST_APPROVAL_REJECTED = 'FIRST_APPROVAL_REJECTED', _('First Approval Rejected')
        SECOND_APPROVAL_APPROVED = 'SECOND_APPROVAL_APPROVED', _('Second Approval Granted')
        SECOND_APPROVAL_REJECTED = 'SECOND_APPROVAL_REJECTED', _('Second Approval Rejected')
        FINAL_APPROVAL = 'FINAL_APPROVAL', _('Final Approval Granted (Task Completed)')
        DEADLINE_EXTENDED = 'DEADLINE_EXTENDED', _('Task Deadline Extended')
        # Phase 6 — Files, Folders, Reports & Documents
        FILE_UPLOADED = 'FILE_UPLOADED', _('File Uploaded')
        FILE_DOWNLOADED = 'FILE_DOWNLOADED', _('File Downloaded')
        FILE_DELETED = 'FILE_DELETED', _('File Deleted')
        FILE_REPLACED = 'FILE_REPLACED', _('File Replaced / New Version')
        FILE_MOVED = 'FILE_MOVED', _('File Moved')
        FOLDER_CREATED = 'FOLDER_CREATED', _('Folder Created')
        FOLDER_RENAMED = 'FOLDER_RENAMED', _('Folder Renamed')
        FOLDER_DELETED = 'FOLDER_DELETED', _('Folder Deleted')
        REPORT_CREATED = 'REPORT_CREATED', _('Task Report Created')
        REPORT_UPDATED = 'REPORT_UPDATED', _('Task Report Updated')
        REPORT_DELETED = 'REPORT_DELETED', _('Task Report Deleted')
        REPORT_EXPORTED = 'REPORT_EXPORTED', _('Task / Report Exported')
        SUBMISSION_VERSION_CREATED = 'SUBMISSION_VERSION_CREATED', _('Submission Version Created')
        # Phase 7 — HR, Employee Governance & KPI
        GRADE_CREATED = 'GRADE_CREATED', _('Employee Grade Created')
        GRADE_UPDATED = 'GRADE_UPDATED', _('Employee Grade Updated')
        EMPLOYEE_GRADE_CHANGED = 'EMPLOYEE_GRADE_CHANGED', _('Employee Grade Changed')
        EMPLOYEE_DEPARTMENT_CHANGED = 'EMPLOYEE_DEPARTMENT_CHANGED', _('Employee Department Changed')
        EMPLOYEE_POSITION_CHANGED = 'EMPLOYEE_POSITION_CHANGED', _('Employee Position Changed')
        EMPLOYEE_SUPERVISOR_CHANGED = 'EMPLOYEE_SUPERVISOR_CHANGED', _('Employee Supervisor Changed')
        EMPLOYEE_STATUS_CHANGED = 'EMPLOYEE_STATUS_CHANGED', _('Employee Employment Status Changed')
        HR_PERMISSION_CHANGED = 'HR_PERMISSION_CHANGED', _('HR Authority Permissions Changed')
        KPI_CATEGORY_CREATED = 'KPI_CATEGORY_CREATED', _('KPI Category Created')
        KPI_DEFINITION_CREATED = 'KPI_DEFINITION_CREATED', _('KPI Definition Created')
        KPI_DEFINITION_UPDATED = 'KPI_DEFINITION_UPDATED', _('KPI Definition Updated')
        KPI_ASSIGNED = 'KPI_ASSIGNED', _('KPI Assigned to Employee')
        KPI_RESULT_RECORDED = 'KPI_RESULT_RECORDED', _('KPI Result Recorded')
        KPI_RESULT_APPROVED = 'KPI_RESULT_APPROVED', _('KPI Result Approved')
        KPI_PERIOD_CREATED = 'KPI_PERIOD_CREATED', _('KPI Period Created')
        KPI_PERIOD_CLOSED = 'KPI_PERIOD_CLOSED', _('KPI Period Closed')
        KPI_CALCULATED = 'KPI_CALCULATED', _('KPI Calculated')
        KPI_RECALCULATED = 'KPI_RECALCULATED', _('KPI Recalculated')
        KPI_VERIFIED = 'KPI_VERIFIED', _('KPI Period Verified by HR')
        KPI_SUBMITTED_FOR_RECTOR = 'KPI_SUBMITTED_FOR_RECTOR', _('KPI Submitted for Rector Approval')
        KPI_RECTOR_APPROVED = 'KPI_RECTOR_APPROVED', _('KPI Rector Approved')
        KPI_RECTOR_REJECTED = 'KPI_RECTOR_REJECTED', _('KPI Rector Rejected')
        KPI_RECTOR_SIGNED = 'KPI_RECTOR_SIGNED', _('KPI Rector Signed')
        KPI_LOCKED = 'KPI_LOCKED', _('KPI Locked')
        KPI_CORRECTION_REQUESTED = 'KPI_CORRECTION_REQUESTED', _('KPI Correction Requested')
        KPI_CORRECTION_APPROVED = 'KPI_CORRECTION_APPROVED', _('KPI Correction Approved')
        KPI_CORRECTION_REJECTED = 'KPI_CORRECTION_REJECTED', _('KPI Correction Rejected')
        # Phase 8 — Payroll, Compensation & Performance-Based Salary System
        SALARY_CREATED = 'SALARY_CREATED', _('Salary Profile Created')
        SALARY_UPDATED = 'SALARY_UPDATED', _('Salary Profile Updated')
        SALARY_DEACTIVATED = 'SALARY_DEACTIVATED', _('Salary Profile Deactivated')
        SALARY_CHANGED = 'SALARY_CHANGED', _('Employee Salary Changed')
        PAYROLL_PERIOD_CREATED = 'PAYROLL_PERIOD_CREATED', _('Payroll Period Created')
        PAYROLL_PERIOD_OPENED = 'PAYROLL_PERIOD_OPENED', _('Payroll Period Opened')
        PAYROLL_CALCULATED = 'PAYROLL_CALCULATED', _('Payroll Calculated')
        PAYROLL_SUBMITTED = 'PAYROLL_SUBMITTED', _('Payroll Submitted for Approval')
        PAYROLL_APPROVED = 'PAYROLL_APPROVED', _('Payroll Approved')
        PAYROLL_CANCELLED = 'PAYROLL_CANCELLED', _('Payroll Cancelled')
        PAYROLL_PAID = 'PAYROLL_PAID', _('Payroll Marked as Paid')
        PAYROLL_CLOSED = 'PAYROLL_CLOSED', _('Payroll Period Closed')
        PAYROLL_ADJUSTMENT_CREATED = 'PAYROLL_ADJUSTMENT_CREATED', _('Payroll Adjustment Created')
        PAYROLL_ADJUSTMENT_APPROVED = 'PAYROLL_ADJUSTMENT_APPROVED', _('Payroll Adjustment Approved')
        PAYROLL_EXPORT_CREATED = 'PAYROLL_EXPORT_CREATED', _('Payroll Export Generated')
        # Governance & Privacy Audit Actions
        ROLE_ASSIGNED = 'ROLE_ASSIGNED', _('Role Assigned')
        ROLE_REMOVED = 'ROLE_REMOVED', _('Role Removed')
        RECTOR_ASSIGNED = 'RECTOR_ASSIGNED', _('Rector Assigned')
        VICE_RECTOR_ASSIGNED = 'VICE_RECTOR_ASSIGNED', _('Vice Rector Assigned')
        FINANCE_ROLE_ASSIGNED = 'FINANCE_ROLE_ASSIGNED', _('Finance Role Assigned')
        PAYROLL_PERMISSION_CHANGED = 'PAYROLL_PERMISSION_CHANGED', _('Payroll Permissions Changed')
        SALARY_VIEWED = 'SALARY_VIEWED', _('Salary Viewed')
        # Phase 9 — Electronic Signature, QR Verification & Cryptographic Task Signing
        SIGNATURE_CREATED = 'SIGNATURE_CREATED', _('Electronic Signature Created')
        SIGNATURE_VERIFIED = 'SIGNATURE_VERIFIED', _('Electronic Signature Verified')
        SIGNATURE_REVOKED = 'SIGNATURE_REVOKED', _('Electronic Signature Revoked')
        SIGNATURE_VERIFICATION_FAILED = 'SIGNATURE_VERIFICATION_FAILED', _('Signature Verification Failed')
        SIGNATURE_KEY_ROTATED = 'SIGNATURE_KEY_ROTATED', _('Signature Key Rotated')
        # Phase 10 — Advanced Analytics, Executive Monitoring & Reporting
        ANALYTICS_VIEWED = 'ANALYTICS_VIEWED', _('Analytics Dashboard Viewed')
        ANALYTICS_EXPORTED = 'ANALYTICS_EXPORTED', _('Analytics Report Exported')
        REPORT_GENERATED = 'REPORT_GENERATED', _('Report Generated')
        # Phase 11 — Automation, SLA & Escalation
        AUTOMATION_EXECUTED = 'AUTOMATION_EXECUTED', _('Automation Rule Executed')
        AUTOMATION_FAILED = 'AUTOMATION_FAILED', _('Automation Rule Failed')
        RULE_CREATED = 'RULE_CREATED', _('Automation Rule Created')
        RULE_UPDATED = 'RULE_UPDATED', _('Automation Rule Updated')
        RULE_DISABLED = 'RULE_DISABLED', _('Automation Rule Disabled')
        SLA_BREACHED = 'SLA_BREACHED', _('SLA Threshold Breached')
        ESCALATION_TRIGGERED = 'ESCALATION_TRIGGERED', _('Task / Approval Escalation Triggered')
        RECURRING_TASK_GENERATED = 'RECURRING_TASK_GENERATED', _('Recurring Task Generated')
        # Phase 12 — Communication & Integrations
        NOTIFICATION_DISPATCHED = 'NOTIFICATION_DISPATCHED', _('Notification Dispatched')
        TELEGRAM_LINKED = 'TELEGRAM_LINKED', _('Telegram Account Linked')
        TELEGRAM_UNLINKED = 'TELEGRAM_UNLINKED', _('Telegram Account Unlinked')
        PREFERENCES_UPDATED = 'PREFERENCES_UPDATED', _('Notification Preferences Updated')
        # Phase 13 — Operations & Requests
        REQUEST_SUBMITTED = 'REQUEST_SUBMITTED', _('University Request Submitted')
        REQUEST_APPROVED = 'REQUEST_APPROVED', _('University Request Approved')
        REQUEST_REJECTED = 'REQUEST_REJECTED', _('University Request Rejected')
        REQUEST_CANCELLED = 'REQUEST_CANCELLED', _('University Request Cancelled')
        DOCUMENT_ROUTED = 'DOCUMENT_ROUTED', _('Document Routed')
        DOCUMENT_VERSION_CREATED = 'DOCUMENT_VERSION_CREATED', _('Document Version Created')
        # Phase 14 — AI Assistant & Intelligence
        AI_REQUESTED = 'AI_REQUESTED', _('AI Assistant Query Requested')
        AI_RESPONSE_GENERATED = 'AI_RESPONSE_GENERATED', _('AI Assistant Response Generated')
        RISK_DETECTED = 'RISK_DETECTED', _('Management Risk Detected')
        # Phase 15 — Security & System Operations
        SECURITY_ALERT = 'SECURITY_ALERT', _('Security Alert Recorded')
        BACKUP_COMPLETED = 'BACKUP_COMPLETED', _('System Backup Completed')
        BACKUP_RESTORED = 'BACKUP_RESTORED', _('System Backup Restored')



    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('actor'),
        on_delete=models.SET_NULL,
        related_name='audit_logs',
        null=True,
        blank=True,
    )
    action = models.CharField(_('action'), max_length=64, choices=Actions.choices)
    target_repr = models.CharField(_('target'), max_length=255, blank=True)
    details = models.JSONField(_('details'), default=dict, blank=True)
    ip_address = models.GenericIPAddressField(_('IP address'), null=True, blank=True)
    created_at = models.DateTimeField(_('timestamp'), auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action']),
            models.Index(fields=['created_at']),
            models.Index(fields=['actor', 'created_at']),
        ]
        verbose_name = _('audit log')
        verbose_name_plural = _('audit logs')

    def __str__(self):
        actor_name = self.actor.display_name if self.actor else _('System')
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_name} -> {self.get_action_display()}: {self.target_repr}"


def log_audit(actor, action: str, target_repr: str = '', details: dict | None = None, request=None) -> AuditLog:
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')

    return AuditLog.objects.create(
        actor=actor if (actor and actor.is_authenticated) else None,
        action=action,
        target_repr=str(target_repr)[:255],
        details=details or {},
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Notification — Phase 5: Persistent in-app notifications
# ---------------------------------------------------------------------------

class Notification(models.Model):

    class NotificationType(models.TextChoices):
        TASK_ASSIGNED = 'TASK_ASSIGNED', _('Task Assigned')
        TASK_SUBMITTED = 'TASK_SUBMITTED', _('Task Submitted for First Approval')
        FIRST_APPROVAL_APPROVED = 'FIRST_APPROVAL_APPROVED', _('First Approval Granted')
        FIRST_APPROVAL_REJECTED = 'FIRST_APPROVAL_REJECTED', _('First Approval Rejected')
        FINAL_APPROVED = 'FINAL_APPROVED', _('Task Successfully Completed')
        FINAL_REJECTED = 'FINAL_REJECTED', _('Task Rejected')
        DEADLINE_EXTENDED = 'DEADLINE_EXTENDED', _('Deadline Extended')
        FILE_UPLOADED = 'FILE_UPLOADED', _('New File Evidence Uploaded')
        REPORT_CREATED = 'REPORT_CREATED', _('New Work Report Created')
        REPORT_SUBMITTED = 'REPORT_SUBMITTED', _('Work Report Submitted for Review')
        # Phase 8 — Payroll Notifications
        PAYROLL_APPROVED = 'PAYROLL_APPROVED', _('Payroll Approved')
        PAYROLL_PAID = 'PAYROLL_PAID', _('Payroll Paid')
        SALARY_CHANGED = 'SALARY_CHANGED', _('Salary Updated')
        PAYROLL_ADJUSTMENT = 'PAYROLL_ADJUSTMENT', _('Payroll Adjustment Updated')
        KPI_PERIOD_OPENED = 'KPI_PERIOD_OPENED', _('KPI Period Opened')
        KPI_ASSIGNED = 'KPI_ASSIGNED', _('KPI Assigned')
        KPI_EVALUATION_REQUIRED = 'KPI_EVALUATION_REQUIRED', _('KPI Evaluation Required')
        KPI_HR_VERIFIED = 'KPI_HR_VERIFIED', _('KPI Period Verified by HR')
        KPI_RECTOR_APPROVED = 'KPI_RECTOR_APPROVED', _('KPI Period Approved by Rector')
        KPI_RECTOR_REJECTED = 'KPI_RECTOR_REJECTED', _('KPI Period Rejected by Rector')
        KPI_SIGNED = 'KPI_SIGNED', _('KPI Period Signed by Rector')
        KPI_CORRECTION = 'KPI_CORRECTION', _('KPI Correction Updated')
        GENERAL = 'GENERAL', _('General Notification')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('recipient'),
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(
        _('notification type'),
        max_length=40,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )
    title = models.CharField(_('title'), max_length=255)
    message = models.TextField(_('message'))
    task = models.ForeignKey(
        'tasks.Task',
        verbose_name=_('task'),
        on_delete=models.SET_NULL,
        related_name='notifications',
        null=True,
        blank=True,
    )
    link = models.CharField(_('link'), max_length=500, blank=True)
    is_read = models.BooleanField(_('is read'), default=False)
    read_at = models.DateTimeField(_('read at'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', '-created_at']),
        ]
        verbose_name = _('notification')
        verbose_name_plural = _('notifications')

    def __str__(self):
        return f"Notification to {self.recipient}: {self.title}"


def create_notification(
    recipient,
    notification_type: str,
    title: str,
    message: str,
    task=None,
    link: str = ''
) -> Notification:
    if not recipient:
        return None
    return Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        task=task,
        link=link,
    )
