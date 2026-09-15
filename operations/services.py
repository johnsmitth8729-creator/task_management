import logging
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import Role
from communication.dispatcher import (
    NotificationCategory,
    NotificationDispatcher,
)
from core.models import AuditLog, Notification, log_audit
from operations.models import (
    DocumentVersion,
    RequestApprovalStep,
    RequestType,
    UniversityDocument,
    UniversityRequest,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class RequestWorkflowEngine:
    """
    State machine and multi-tier approval chain orchestrator for university requests.
    """

    @classmethod
    @transaction.atomic
    def submit_request(
        cls,
        request_type: RequestType,
        requester,
        subject: str,
        details_payload: dict = None,
        is_urgent: bool = False,
    ) -> UniversityRequest:
        """
        Creates a UniversityRequest and generates its sequential approval pipeline.
        """
        dept = requester.department if hasattr(requester, 'department') else None

        uni_req = UniversityRequest.objects.create(
            request_type=request_type,
            requester=requester,
            department=dept,
            subject=subject,
            details_payload=details_payload or {},
            is_urgent=is_urgent,
            status=UniversityRequest.Status.SUBMITTED,
            current_step_number=1,
        )

        cls.build_approval_chain(uni_req)

        log_audit(
            actor=requester,
            action=AuditLog.Actions.REQUEST_SUBMITTED,
            target_repr=f"Request: {uni_req.request_number}",
            details={'subject': subject, 'type': request_type.name, 'urgent': is_urgent}
        )

        # Notify initial approver
        first_step = uni_req.approval_steps.filter(step_number=1).first()
        if first_step:
            cls._notify_step_approver(first_step)

        return uni_req

    @classmethod
    def build_approval_chain(cls, uni_req: UniversityRequest):
        """
        Builds sequential RequestApprovalStep records according to RequestType config.
        """
        rt = uni_req.request_type
        dept = uni_req.department
        step_num = 1

        # 1. Department Head
        if rt.requires_dept_head_approval:
            approver = dept.head if (dept and dept.head) else None
            RequestApprovalStep.objects.create(
                request=uni_req,
                step_number=step_num,
                approver_role=RequestApprovalStep.ApproverRole.DEPARTMENT_HEAD,
                assigned_approver=approver,
            )
            step_num += 1

        # 2. Supervising Vice Rector / Dean
        if rt.requires_dean_or_vr_approval:
            vr = None
            if dept:
                vr = User.objects.filter(
                    department_responsibilities__department=dept,
                    department_responsibilities__is_active=True
                ).first()
            RequestApprovalStep.objects.create(
                request=uni_req,
                step_number=step_num,
                approver_role=RequestApprovalStep.ApproverRole.VICE_RECTOR,
                assigned_approver=vr,
            )
            step_num += 1

        # 3. HR Manager
        if rt.requires_hr_approval:
            hr_user = User.objects.filter(roles__code=Role.Codes.HR, is_active=True).first()
            RequestApprovalStep.objects.create(
                request=uni_req,
                step_number=step_num,
                approver_role=RequestApprovalStep.ApproverRole.HR_MANAGER,
                assigned_approver=hr_user,
            )
            step_num += 1

        # 4. Finance Director
        if rt.requires_finance_approval:
            fin_user = User.objects.filter(roles__code=Role.Codes.FINANCE, is_active=True).first()
            RequestApprovalStep.objects.create(
                request=uni_req,
                step_number=step_num,
                approver_role=RequestApprovalStep.ApproverRole.FINANCE_DIRECTOR,
                assigned_approver=fin_user,
            )
            step_num += 1

        # 5. Rector
        if rt.requires_rector_approval:
            rector_user = User.objects.filter(roles__code=Role.Codes.RECTOR, is_active=True).first()
            RequestApprovalStep.objects.create(
                request=uni_req,
                step_number=step_num,
                approver_role=RequestApprovalStep.ApproverRole.RECTOR,
                assigned_approver=rector_user,
            )
            step_num += 1

        # Fallback if no steps were enabled
        if step_num == 1:
            uni_req.status = UniversityRequest.Status.APPROVED
            uni_req.resolved_at = timezone.now()
            uni_req.save(update_fields=['status', 'resolved_at'])

    @classmethod
    @transaction.atomic
    def process_approval_step(
        cls,
        step: RequestApprovalStep,
        user,
        decision: str,
        comments: str = "",
    ) -> bool:
        """
        Executes an approval or rejection decision on an approval step.
        """
        if step.status != RequestApprovalStep.StepStatus.PENDING:
            return False

        uni_req = step.request
        step.decided_by = user
        step.decided_at = timezone.now()
        step.comments = comments

        if decision == 'APPROVED':
            step.status = RequestApprovalStep.StepStatus.APPROVED
            step.save()

            # Check next step
            next_step = uni_req.approval_steps.filter(step_number=step.step_number + 1).first()
            if next_step:
                uni_req.current_step_number = next_step.step_number
                uni_req.status = UniversityRequest.Status.IN_REVIEW
                uni_req.save(update_fields=['current_step_number', 'status', 'updated_at'])
                cls._notify_step_approver(next_step)
            else:
                # All steps approved!
                uni_req.status = UniversityRequest.Status.APPROVED
                uni_req.resolved_at = timezone.now()
                uni_req.save(update_fields=['status', 'resolved_at', 'updated_at'])

                # Notify requester of full approval
                NotificationDispatcher.dispatch(
                    recipient=uni_req.requester,
                    title=f"[APPROVED] Request {uni_req.request_number}",
                    message=f"Your request '{uni_req.subject}' has been fully approved.",
                    category=NotificationCategory.WORKFLOW_APPROVAL,
                )
                log_audit(
                    actor=user,
                    action=AuditLog.Actions.REQUEST_APPROVED,
                    target_repr=f"Request: {uni_req.request_number}",
                    details={'subject': uni_req.subject, 'step': step.step_number}
                )

        elif decision == 'REJECTED':
            step.status = RequestApprovalStep.StepStatus.REJECTED
            step.save()

            # Entire request marked as rejected
            uni_req.status = UniversityRequest.Status.REJECTED
            uni_req.resolved_at = timezone.now()
            uni_req.save(update_fields=['status', 'resolved_at', 'updated_at'])

            # Mark remaining steps skipped
            uni_req.approval_steps.filter(step_number__gt=step.step_number).update(
                status=RequestApprovalStep.StepStatus.SKIPPED
            )

            # Notify requester of rejection
            NotificationDispatcher.dispatch(
                recipient=uni_req.requester,
                title=f"[REJECTED] Request {uni_req.request_number}",
                message=f"Your request '{uni_req.subject}' was rejected at step {step.step_number} ({step.get_approver_role_display()}): {comments}",
                category=NotificationCategory.WORKFLOW_APPROVAL,
            )
            log_audit(
                actor=user,
                action=AuditLog.Actions.REQUEST_REJECTED,
                target_repr=f"Request: {uni_req.request_number}",
                details={'subject': uni_req.subject, 'step': step.step_number, 'reason': comments}
            )

        return True

    @classmethod
    def _notify_step_approver(cls, step: RequestApprovalStep):
        """
        Dispatches pending review notification to the assigned approver or role holders.
        """
        recipients = []
        if step.assigned_approver:
            recipients.append(step.assigned_approver)
        else:
            role_map = {
                RequestApprovalStep.ApproverRole.DEPARTMENT_HEAD: Role.Codes.DEPARTMENT_HEAD,
                RequestApprovalStep.ApproverRole.VICE_RECTOR: Role.Codes.VICE_RECTOR,
                RequestApprovalStep.ApproverRole.HR_MANAGER: Role.Codes.HR,
                RequestApprovalStep.ApproverRole.FINANCE_DIRECTOR: Role.Codes.FINANCE,
                RequestApprovalStep.ApproverRole.RECTOR: Role.Codes.RECTOR,
            }
            code = role_map.get(step.approver_role)
            if code:
                recipients = list(User.objects.filter(roles__code=code, is_active=True))

        for recipient in recipients:
            NotificationDispatcher.dispatch(
                recipient=recipient,
                title=f"[Approval Required] {step.request.request_number}",
                message=f"Request '{step.request.subject}' from {step.request.requester.display_name} requires your review as {step.get_approver_role_display()}.",
                category=NotificationCategory.WORKFLOW_APPROVAL,
            )

    @classmethod
    def cancel_request(cls, uni_req: UniversityRequest, user) -> bool:
        if uni_req.requester != user and not user.is_superuser:
            return False
        if uni_req.status in [UniversityRequest.Status.APPROVED, UniversityRequest.Status.COMPLETED]:
            return False

        uni_req.status = UniversityRequest.Status.CANCELLED
        uni_req.resolved_at = timezone.now()
        uni_req.save(update_fields=['status', 'resolved_at', 'updated_at'])
        uni_req.approval_steps.filter(status=RequestApprovalStep.StepStatus.PENDING).update(
            status=RequestApprovalStep.StepStatus.SKIPPED
        )
        log_audit(
            actor=user,
            action=AuditLog.Actions.REQUEST_CANCELLED,
            target_repr=f"Request: {uni_req.request_number}",
            details={'subject': uni_req.subject}
        )
        return True


class DocumentService:
    """
    Manages official university promulgated documents and versioning.
    """

    @classmethod
    def add_version(cls, document: UniversityDocument, file, changelog: str, user) -> DocumentVersion:
        new_version_num = document.version + 1
        doc_version = DocumentVersion.objects.create(
            document=document,
            version_number=new_version_num,
            file=file,
            changelog=changelog,
            uploaded_by=user,
        )
        document.version = new_version_num
        document.file = file
        document.save(update_fields=['version', 'file', 'updated_at'])

        log_audit(
            actor=user,
            action=AuditLog.Actions.DOCUMENT_VERSION_CREATED,
            target_repr=f"Document: {document.doc_number} v{new_version_num}",
            details={'changelog': changelog}
        )
        return doc_version
