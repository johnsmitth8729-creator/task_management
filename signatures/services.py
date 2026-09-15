import secrets
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from core.models import AuditLog, Notification, create_notification, log_audit
from signatures.crypto import (
    SignatureKeyProvider,
    canonical_json,
    compute_sha256,
    sign_data,
    verify_signature_bytes,
)
from signatures.models import (
    ElectronicSignature,
    SignatureSnapshot,
    SignatureVerificationEvent,
)
from signatures.permissions import can_revoke_signature, can_sign_task
from tasks.models import Task, TaskApproval


def generate_secure_verification_id() -> str:
    """Generates a unique, non-guessable verification ID (e.g., SIG-2026-A1B2C3D4E5F6)."""
    year = timezone.now().year
    random_part = secrets.token_hex(6).upper()
    return f"SIG-{year}-{random_part}"


def build_canonical_payload(task: Task, signer: User, signature_type: str) -> dict[str, Any]:
    """
    Builds the deterministic, immutable business record representing the completed task.
    Includes task identity, departmental metadata, assignees, final approval,
    and evidence file SHA-256 checksums.
    """
    final_approval = task.approvals.filter(
        stage=TaskApproval.Stage.FINAL_APPROVAL,
        decision=TaskApproval.Decision.APPROVED,
    ).order_by('-created_at').first()

    # Collect active evidence files
    evidence_files = []
    for f in task.files.filter(is_active=True).order_by('created_at'):
        evidence_files.append({
            'file_id': str(f.id),
            'filename': f.original_filename,
            'sha256': f.checksum or compute_sha256(f.file.read() if f.file else b''),
            'category': f.category,
            'version': f.version,
        })

    # Collect active report hashes if any
    reports_data = []
    for rep in task.reports.filter(status='APPROVED').order_by('created_at'):
        rep_canonical = f"{rep.title}|{rep.reporting_period}|{rep.summary}|{rep.results}"
        reports_data.append({
            'report_id': str(rep.id),
            'title': rep.title,
            'version': rep.version,
            'content_hash': compute_sha256(rep_canonical),
        })

    # Collect primary & all assignees
    assignees_data = []
    for a in task.assignments.all().select_related('user').order_by('assigned_at'):
        assignees_data.append({
            'user_id': str(a.user.id),
            'username': a.user.username,
            'display_name': a.user.display_name,
            'is_primary': a.is_primary,
        })

    # Build canonical dict with sorted keys & stable types
    payload = {
        'schema_version': 1,
        'signature_version': 1,
        'task_id': str(task.id),
        'task_number': task.task_number,
        'title': task.title,
        'description': task.description or '',
        'responsible_department_id': str(task.responsible_department.id) if task.responsible_department else None,
        'responsible_department_name': task.responsible_department.name if task.responsible_department else None,
        'priority': task.priority,
        'complexity': task.complexity,
        'deadline': task.deadline.isoformat() if task.deadline else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else timezone.now().isoformat(),
        'assignees': assignees_data,
        'final_approval': {
            'approval_id': str(final_approval.id) if final_approval else None,
            'approver_id': str(final_approval.actor.id) if (final_approval and final_approval.actor) else None,
            'approver_name': final_approval.actor.display_name if (final_approval and final_approval.actor) else None,
            'approver_role': final_approval.actor_role_code if final_approval else None,
            'approved_at': final_approval.created_at.isoformat() if final_approval else None,
            'decision': final_approval.decision if final_approval else 'APPROVED',
            'notes': final_approval.reason if final_approval else '',
        },
        'evidence_files': evidence_files,
        'approved_reports': reports_data,
        'signer': {
            'signer_id': str(signer.id),
            'signer_username': signer.username,
            'signer_name': signer.display_name,
            'signer_position': signer.position.name if signer.position else '',
            'signer_department': signer.department.name if signer.department else '',
            'signature_type': signature_type,
        },
    }
    return payload


@transaction.atomic
def sign_task(
    task: Task,
    signer: User,
    request=None,
    signature_type: str | None = None,
) -> ElectronicSignature:
    """
    Executes electronic signing of a completed, final-approved task with cryptographic Ed25519 signature.
    Enforces atomic locking, role authorization, deterministic payload hashing,
    and immutable snapshot generation.
    """
    # 1. Lock task row with select_for_update to prevent concurrency race conditions
    locked_task = Task.objects.select_for_update().get(pk=task.pk)

    # 2. Validate signer authorization and task state
    is_allowed, reason = can_sign_task(signer, locked_task)
    if not is_allowed:
        raise ValidationError(reason)

    # 3. Determine signature type
    if not signature_type:
        if signer.is_superuser:
            signature_type = ElectronicSignature.SignatureType.SUPERADMIN_SIGNATURE
        elif signer.is_rector or signer.is_acting_rector:
            signature_type = ElectronicSignature.SignatureType.RECTOR_SIGNATURE
        elif signer.is_vice_rector:
            signature_type = ElectronicSignature.SignatureType.VICE_RECTOR_SIGNATURE
        else:
            signature_type = ElectronicSignature.SignatureType.OTHER_AUTHORIZED_SIGNATURE

    # 4. Generate unique, non-sequential verification identifiers
    verification_id = generate_secure_verification_id()
    while ElectronicSignature.objects.filter(verification_id=verification_id).exists():
        verification_id = generate_secure_verification_id()

    verification_token = secrets.token_urlsafe(32)

    # 5. Build canonical representation and compute payload hash
    canonical_payload = build_canonical_payload(locked_task, signer, signature_type)
    canonical_bytes = canonical_json(canonical_payload)
    payload_hash = compute_sha256(canonical_bytes)

    # Snapshot hash represents canonical bytes hash
    snapshot_hash = payload_hash

    # 6. Retrieve active signing key and compute Ed25519 cryptographic signature
    active_private_key = SignatureKeyProvider.get_active_private_key()
    active_public_key = SignatureKeyProvider.get_active_public_key()
    algorithm = SignatureKeyProvider.get_algorithm()
    key_version = SignatureKeyProvider.get_key_version()
    public_key_pem = SignatureKeyProvider.export_public_key_pem(active_public_key)

    # Cryptographically sign the canonical bytes
    signature_value = sign_data(active_private_key, canonical_bytes)

    now = timezone.now()

    # 7. Persist ElectronicSignature record
    signature = ElectronicSignature.objects.create(
        task=locked_task,
        signer=signer,
        signature_type=signature_type,
        status=ElectronicSignature.Status.SIGNED,
        signed_at=now,
        verification_id=verification_id,
        verification_token=verification_token,
        snapshot_hash=snapshot_hash,
        payload_hash=payload_hash,
        signature_value=signature_value,
        algorithm=algorithm,
        key_version=key_version,
        public_key_reference=public_key_pem,
    )

    # 8. Persist immutable SignatureSnapshot record
    SignatureSnapshot.objects.create(
        signature=signature,
        canonical_payload=canonical_payload,
        payload_hash=payload_hash,
        schema_version=1,
    )

    # 8.1. Generate official signed PDF document with logo, task info, execution process & QR code
    from django.core.files.base import ContentFile
    from files.models import TaskFile
    from signatures.pdf import generate_signed_task_pdf

    try:
        pdf_buffer = generate_signed_task_pdf(signature, request=request)
        pdf_filename = f"Topshiriq_{locked_task.task_number}_Elektron_Imzo_{signature.verification_id}.pdf"
        signature.signed_pdf.save(pdf_filename, ContentFile(pdf_buffer.getvalue()), save=True)

        TaskFile.objects.create(
            task=locked_task,
            uploaded_by=signer,
            file=signature.signed_pdf,
            original_filename=pdf_filename,
            file_size=len(pdf_buffer.getvalue()),
            mime_type='application/pdf',
            category=TaskFile.FileCategory.EVIDENCE,
            description=str(_('Official electronically signed task completion certificate with QR code')),
        )
    except Exception:
        pass

    # 9. Audit log entry
    log_audit(
        actor=signer,
        action=AuditLog.Actions.SIGNATURE_CREATED,
        target_repr=f"{locked_task.task_number}: electronically signed by {signer.display_name} ({verification_id})",
        details={
            'signature_id': str(signature.id),
            'verification_id': verification_id,
            'algorithm': algorithm,
            'key_version': key_version,
            'payload_hash': payload_hash,
        },
        request=request,
    )

    # 10. Dispatch notifications to task participants
    # Notify assignees
    for assignment in locked_task.assignments.all().select_related('user'):
        create_notification(
            recipient=assignment.user,
            notification_type=Notification.NotificationType.FINAL_APPROVED,
            title=_('Task Electronically Signed'),
            message=_('Completed task {task_num} has received official electronic signature by {signer} ({ver_id}).').format(
                task_num=locked_task.task_number,
                signer=signer.display_name,
                ver_id=verification_id,
            ),
            task=locked_task,
            link=f"/tasks/{locked_task.id}/",
        )

    # Notify Department Head if available
    if locked_task.responsible_department:
        dept_head = locked_task.responsible_department.head or User.objects.filter(
            department=locked_task.responsible_department,
            roles__code='DEPARTMENT_HEAD',
            is_active=True,
        ).first()
        if dept_head and dept_head.id != signer.id:
            create_notification(
                recipient=dept_head,
                notification_type=Notification.NotificationType.FINAL_APPROVED,
                title=_('Task Electronically Signed'),
                message=_('Task {task_num} in your department was electronically signed by {signer}.').format(
                    task_num=locked_task.task_number,
                    signer=signer.display_name,
                ),
                task=locked_task,
                link=f"/tasks/{locked_task.id}/",
            )

    return signature


def verify_signature(
    verification_id_or_token: str,
    request=None,
) -> dict[str, Any]:
    """
    Public and internal verification engine.
    Independently verifies:
    1. Signature existence and record status
    2. Snapshot payload reconstruction and SHA-256 hash integrity
    3. Asymmetric cryptographic Ed25519 signature validity against public key
    4. Tamper detection on payload or signature alteration
    5. Returns safe public metadata (no salary, no personal phone/email, no private notes)
    """
    identifier = verification_id_or_token.strip()
    signature = (
        ElectronicSignature.objects.filter(verification_id=identifier)
        .select_related('task', 'signer', 'signer__position', 'signer__department', 'snapshot')
        .first()
        or ElectronicSignature.objects.filter(verification_token=identifier)
        .select_related('task', 'signer', 'signer__position', 'signer__department', 'snapshot')
        .first()
    )

    client_ip = request.META.get('REMOTE_ADDR') if request else None
    user_agent = request.META.get('HTTP_USER_AGENT', '') if request else ''

    if not signature:
        # Record failed verification event
        SignatureVerificationEvent.objects.create(
            verification_id=identifier,
            is_valid=False,
            failure_reason='SIGNATURE_NOT_FOUND',
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return {
            'is_valid': False,
            'status': 'NOT_FOUND',
            'error_message': _('No signature record found for the provided verification identifier.'),
        }

    # If revoked
    if signature.status == ElectronicSignature.Status.REVOKED or signature.revoked_at is not None:
        SignatureVerificationEvent.objects.create(
            signature=signature,
            verification_id=signature.verification_id,
            is_valid=False,
            failure_reason='SIGNATURE_REVOKED',
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return {
            'is_valid': False,
            'status': 'REVOKED',
            'verification_id': signature.verification_id,
            'task_number': signature.task.task_number if signature.task else f"KPI-{signature.kpi_period.code}",
            'task_title': signature.task.title if signature.task else f"KPI Period {signature.kpi_period.name}",
            'department_name': signature.task.responsible_department.name if (signature.task and signature.task.responsible_department) else str(_('University Executive Directorate')),
            'signer_name': signature.signer.display_name,
            'signer_position': signature.signer.position.name if signature.signer.position else '',
            'signed_at': signature.signed_at,
            'revoked_at': signature.revoked_at,
            'revocation_reason': signature.revocation_reason,
            'error_message': _('This electronic signature has been revoked by university authorities.'),
        }

    # Load immutable snapshot
    snapshot = getattr(signature, 'snapshot', None)
    if not snapshot:
        SignatureVerificationEvent.objects.create(
            signature=signature,
            verification_id=signature.verification_id,
            is_valid=False,
            failure_reason='SNAPSHOT_MISSING',
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return {
            'is_valid': False,
            'status': 'INVALID',
            'error_message': _('Signed record snapshot is missing or corrupted.'),
        }

    # Re-serialize canonical payload to canonical bytes
    recomputed_bytes = canonical_json(snapshot.canonical_payload)
    recomputed_hash = compute_sha256(recomputed_bytes)

    # Tamper check 1: Compare recomputed hash with stored payload hash and snapshot hash
    if (
        recomputed_hash != signature.payload_hash
        or recomputed_hash != snapshot.payload_hash
        or recomputed_hash != signature.snapshot_hash
    ):
        SignatureVerificationEvent.objects.create(
            signature=signature,
            verification_id=signature.verification_id,
            is_valid=False,
            failure_reason='PAYLOAD_INTEGRITY_TAMPERED',
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return {
            'is_valid': False,
            'status': 'INVALID',
            'error_message': _('Integrity failure: The signed payload has been altered or tampered with.'),
        }

    # Cryptographic verification: Load public key for key version and verify signature bytes
    public_key = SignatureKeyProvider.get_public_key_for_version(
        signature.key_version,
        stored_pem=signature.public_key_reference,
    )
    if not public_key:
        SignatureVerificationEvent.objects.create(
            signature=signature,
            verification_id=signature.verification_id,
            is_valid=False,
            failure_reason='PUBLIC_KEY_UNAVAILABLE',
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return {
            'is_valid': False,
            'status': 'INVALID',
            'error_message': _('Public key for signature verification could not be resolved.'),
        }

    crypto_valid = verify_signature_bytes(
        public_key,
        recomputed_bytes,
        signature.signature_value,
    )

    if not crypto_valid:
        SignatureVerificationEvent.objects.create(
            signature=signature,
            verification_id=signature.verification_id,
            is_valid=False,
            failure_reason='CRYPTOGRAPHIC_SIGNATURE_INVALID',
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return {
            'is_valid': False,
            'status': 'INVALID',
            'error_message': _('Cryptographic signature verification failed: digital signature mismatch.'),
        }

    # Verification passed!
    SignatureVerificationEvent.objects.create(
        signature=signature,
        verification_id=signature.verification_id,
        is_valid=True,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    # Prepare safe public verification response
    final_approval_info = snapshot.canonical_payload.get('final_approval', {})
    approved_at_str = final_approval_info.get('approved_at')

    return {
        'is_valid': True,
        'status': 'VALID',
        'verification_id': signature.verification_id,
        'task_number': signature.task.task_number if signature.task else f"KPI-{signature.kpi_period.code}",
        'task_title': signature.task.title if signature.task else f"KPI Period {signature.kpi_period.name}",
        'department_name': signature.task.responsible_department.name if (signature.task and signature.task.responsible_department) else str(_('University Executive Directorate')),
        'signer_name': signature.signer.display_name,
        'signer_position': signature.signer.position.name if signature.signer.position else '',
        'signature_type_display': signature.get_signature_type_display(),
        'signed_at': signature.signed_at,
        'final_approval_date': approved_at_str,
        'algorithm': signature.algorithm,
        'key_version': signature.key_version,
        'payload_hash': signature.payload_hash,
        'integrity_status': _('VERIFIED (Immutable Cryptographic Match)'),
    }


@transaction.atomic
def revoke_signature(
    signature: ElectronicSignature,
    actor: User,
    reason: str,
    request=None,
) -> ElectronicSignature:
    """
    Revokes an active electronic signature.
    Only authorized Superadmin or Rector can perform revocation.
    Mandatory reason required. Preserves historical audit record.
    """
    if not can_revoke_signature(actor, signature):
        raise ValidationError(_('You do not have authority to revoke this signature.'))

    reason = (reason or '').strip()
    if not reason:
        raise ValidationError(_('A revocation reason is required.'))

    if signature.status == ElectronicSignature.Status.REVOKED:
        raise ValidationError(_('This signature is already revoked.'))

    now = timezone.now()
    signature.status = ElectronicSignature.Status.REVOKED
    signature.revoked_at = now
    signature.revoked_by = actor
    signature.revocation_reason = reason
    signature.save(update_fields=['status', 'revoked_at', 'revoked_by', 'revocation_reason'])

    log_audit(
        actor=actor,
        action=AuditLog.Actions.SIGNATURE_REVOKED,
        target_repr=f"{signature.verification_id} revoked by {actor.display_name}",
        details={
            'signature_id': str(signature.id),
            'verification_id': signature.verification_id,
            'reason': reason,
        },
        request=request,
    )

    return signature
