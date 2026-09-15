import base64
import json
import uuid
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric import ed25519
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from core.models import AuditLog, Notification
from organization.models import Department, DepartmentResponsibility, Position
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
from signatures.qr import generate_qr_data_uri, generate_qr_image
from signatures.services import (
    build_canonical_payload,
    revoke_signature,
    sign_task,
    verify_signature,
)
from tasks.models import Task, TaskApproval, TaskAssignment, TaskSubmission

User = get_user_model()


class ElectronicSignatureTests(TestCase):
    """
    Comprehensive test suite for Phase 9 Electronic Signature, QR Verification & Cryptographic Task Signing.
    """

    def setUp(self):
        # Setup Roles
        self.role_rector, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.role_vice_rector, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.role_dept_head, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.role_employee, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})
        self.role_finance, _ = Role.objects.get_or_create(code=Role.Codes.FINANCE, defaults={'name': 'Finance'})
        self.role_hr, _ = Role.objects.get_or_create(code=Role.Codes.HR, defaults={'name': 'HR'})

        # Setup Departments
        self.dept_it = Department.objects.create(name='IT Department', code='IT-TEST', is_active=True)
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN-TEST', is_active=True)

        # Setup Users
        self.superadmin = User.objects.create_superuser(
            username='admin_test',
            email='admin@univ.test',
            password='Password123!',
        )
        self.rector = User.objects.create_user(
            username='rector_test',
            email='rector@univ.test',
            password='Password123!',
            first_name='Rector',
            last_name='Official',
        )
        self.rector.roles.add(self.role_rector)

        self.vice_rector_it = User.objects.create_user(
            username='vr_it_test',
            email='vr_it@univ.test',
            password='Password123!',
            first_name='ViceRector',
            last_name='IT',
        )
        self.vice_rector_it.roles.add(self.role_vice_rector)
        DepartmentResponsibility.objects.create(
            vice_rector=self.vice_rector_it,
            department=self.dept_it,
            is_active=True,
        )

        self.dept_head = User.objects.create_user(
            username='head_test',
            email='head@univ.test',
            password='Password123!',
            first_name='Head',
            last_name='IT',
            department=self.dept_it,
        )
        self.dept_head.roles.add(self.role_dept_head)

        self.employee = User.objects.create_user(
            username='emp_test',
            email='emp@univ.test',
            password='Password123!',
            first_name='Aziz',
            last_name='Employee',
            department=self.dept_it,
        )
        self.employee.roles.add(self.role_employee)

        self.finance_user = User.objects.create_user(
            username='fin_test',
            email='fin@univ.test',
            password='Password123!',
            department=self.dept_fin,
        )
        self.finance_user.roles.add(self.role_finance)

        self.hr_user = User.objects.create_user(
            username='hr_test',
            email='hr@univ.test',
            password='Password123!',
            department=self.dept_it,
        )
        self.hr_user.roles.add(self.role_hr)

        # Setup Completed & Final-Approved Task
        self.task = Task.objects.create(
            task_number='TM-TEST-001',
            title='Campus Network Upgrade Phase 1',
            description='Upgrade core switches and fiber connectivity.',
            creator=self.rector,
            responsible_department=self.dept_it,
            priority=Task.Priority.HIGH,
            complexity=Task.Complexity.COMPLEX,
            status=Task.Status.COMPLETED,
            progress=100,
            deadline=timezone.now().date() + timedelta(days=10),
            completed_at=timezone.now(),
        )

        self.assignment = TaskAssignment.objects.create(
            task=self.task,
            user=self.employee,
            assigned_by=self.dept_head,
            is_primary=True,
            assignment_status=TaskAssignment.AssignmentStatus.APPROVED,
            progress=100,
        )

        self.submission = TaskSubmission.objects.create(
            task=self.task,
            assignment=self.assignment,
            submitted_by=self.employee,
            submission_text='Upgrade completed with zero downtime.',
            status=TaskSubmission.SubmissionStatus.FINAL_APPROVED,
        )

        # Level 1 Approval
        TaskApproval.objects.create(
            task=self.task,
            assignment=self.assignment,
            submission=self.submission,
            stage=TaskApproval.Stage.FIRST_APPROVAL,
            decision=TaskApproval.Decision.APPROVED,
            actor=self.dept_head,
            actor_role_code='DEPARTMENT_HEAD',
        )

        # Level 2 / Final Approval
        self.final_approval = TaskApproval.objects.create(
            task=self.task,
            assignment=self.assignment,
            submission=self.submission,
            stage=TaskApproval.Stage.FINAL_APPROVAL,
            decision=TaskApproval.Decision.APPROVED,
            actor=self.rector,
            actor_role_code='RECTOR',
            reason='All criteria met.',
        )

    # =======================================================================
    # 1. SIGNING AUTHORIZATION TESTS
    # =======================================================================

    def test_employee_cannot_sign(self):
        """Employee cannot electronically sign completed tasks."""
        is_allowed, reason = can_sign_task(self.employee, self.task)
        self.assertFalse(is_allowed)
        with self.assertRaises(ValidationError):
            sign_task(self.task, self.employee)

    def test_department_head_cannot_sign(self):
        """Department Head cannot perform final electronic signature."""
        is_allowed, reason = can_sign_task(self.dept_head, self.task)
        self.assertFalse(is_allowed)
        with self.assertRaises(ValidationError):
            sign_task(self.task, self.dept_head)

    def test_hr_cannot_sign(self):
        """HR role cannot electronically sign completed tasks."""
        is_allowed, reason = can_sign_task(self.hr_user, self.task)
        self.assertFalse(is_allowed)
        with self.assertRaises(ValidationError):
            sign_task(self.task, self.hr_user)

    def test_finance_cannot_sign(self):
        """Finance role cannot electronically sign completed tasks."""
        is_allowed, reason = can_sign_task(self.finance_user, self.task)
        self.assertFalse(is_allowed)
        with self.assertRaises(ValidationError):
            sign_task(self.task, self.finance_user)

    def test_rector_can_sign_final_approved_task(self):
        """Rector has university-wide authority to electronically sign completed tasks."""
        is_allowed, reason = can_sign_task(self.rector, self.task)
        self.assertTrue(is_allowed)
        sig = sign_task(self.task, self.rector)
        self.assertEqual(sig.status, ElectronicSignature.Status.SIGNED)
        self.assertEqual(sig.signer, self.rector)
        self.assertEqual(sig.signature_type, ElectronicSignature.SignatureType.RECTOR_SIGNATURE)
        self.assertTrue(sig.verification_id.startswith('SIG-'))

    def test_vice_rector_cannot_sign_any_task(self):
        """Vice Rector is not authorized to sign any task — only the Rector may sign."""
        is_allowed, reason = can_sign_task(self.vice_rector_it, self.task)
        self.assertFalse(is_allowed)
        self.assertIn('Only the Rector may sign', reason)
        with self.assertRaises(ValidationError):
            sign_task(self.task, self.vice_rector_it)

    def test_vice_rector_cannot_sign_unauthorized_department_task(self):
        """Vice Rector cannot sign tasks for any department — signing is Rector-only."""
        fin_task = Task.objects.create(
            task_number='TM-TEST-FIN-001',
            title='Finance Audit',
            creator=self.rector,
            responsible_department=self.dept_fin,
            status=Task.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        TaskApproval.objects.create(
            task=fin_task,
            stage=TaskApproval.Stage.FINAL_APPROVAL,
            decision=TaskApproval.Decision.APPROVED,
            actor=self.rector,
        )

        is_allowed, reason = can_sign_task(self.vice_rector_it, fin_task)
        self.assertFalse(is_allowed)
        self.assertIn('Only the Rector may sign', reason)
        with self.assertRaises(ValidationError):
            sign_task(fin_task, self.vice_rector_it)

    def test_superadmin_has_administrative_signature_authority(self):
        """Superadmin has administrative signing authority and is recorded as SUPERADMIN_SIGNATURE."""
        is_allowed, reason = can_sign_task(self.superadmin, self.task)
        self.assertTrue(is_allowed)
        sig = sign_task(self.task, self.superadmin)
        self.assertEqual(sig.signature_type, ElectronicSignature.SignatureType.SUPERADMIN_SIGNATURE)

    # =======================================================================
    # 2. WORKFLOW & CONCURRENCY TESTS
    # =======================================================================

    def test_cannot_sign_in_progress_or_draft_task(self):
        """Task must not be signed if it is IN_PROGRESS or DRAFT."""
        self.task.status = Task.Status.IN_PROGRESS
        self.task.save()
        is_allowed, reason = can_sign_task(self.rector, self.task)
        self.assertFalse(is_allowed)
        with self.assertRaises(ValidationError):
            sign_task(self.task, self.rector)

    def test_cannot_sign_rejected_task(self):
        """Task must not be signed if it was rejected."""
        self.final_approval.decision = TaskApproval.Decision.REJECTED
        self.final_approval.save()
        is_allowed, reason = can_sign_task(self.rector, self.task)
        self.assertFalse(is_allowed)

    def test_cannot_sign_without_final_approval_record(self):
        """Task must not be signed if final approval record is missing."""
        self.final_approval.delete()
        is_allowed, reason = can_sign_task(self.rector, self.task)
        self.assertFalse(is_allowed)

    def test_cannot_double_sign_task(self):
        """Once signed, a task cannot be signed again."""
        sign_task(self.task, self.rector)
        is_allowed, reason = can_sign_task(self.rector, self.task)
        self.assertFalse(is_allowed)
        self.assertIn('already been electronically signed', reason)

        with self.assertRaises(ValidationError):
            sign_task(self.task, self.rector)

    # =======================================================================
    # 3. CRYPTOGRAPHIC INTEGRITY & DETERMINISTIC CANONICAL PAYLOAD
    # =======================================================================

    def test_deterministic_canonical_payload(self):
        """
        Tests that canonical serialization is deterministic regardless of key insertion order.
        """
        dict_a = {'z': 1, 'a': 2, 'm': {'k2': 'v2', 'k1': 'v1'}}
        dict_b = {'a': 2, 'm': {'k1': 'v1', 'k2': 'v2'}, 'z': 1}

        bytes_a = canonical_json(dict_a)
        bytes_b = canonical_json(dict_b)

        self.assertEqual(bytes_a, bytes_b)
        self.assertEqual(compute_sha256(bytes_a), compute_sha256(bytes_b))

    def test_valid_signature_verifies(self):
        """A legitimately signed task verifies successfully with VALID status."""
        sig = sign_task(self.task, self.rector)
        res = verify_signature(sig.verification_id)

        self.assertTrue(res['is_valid'])
        self.assertEqual(res['status'], 'VALID')
        self.assertEqual(res['verification_id'], sig.verification_id)
        self.assertEqual(res['task_number'], self.task.task_number)
        self.assertEqual(res['signer_name'], self.rector.display_name)

    def test_tamper_detection_modified_payload_fails_verification(self):
        """Altering the canonical snapshot payload causes immediate verification failure."""
        sig = sign_task(self.task, self.rector)
        snapshot = sig.snapshot

        # Tamper with snapshot payload
        snapshot.canonical_payload['title'] = 'HACKED TITLE'
        snapshot.save()

        res = verify_signature(sig.verification_id)
        self.assertFalse(res['is_valid'])
        self.assertEqual(res['status'], 'INVALID')
        self.assertIn('tampered', res['error_message'])

    def test_tamper_detection_modified_signature_value_fails_verification(self):
        """Altering the signature value causes cryptographic verification failure."""
        sig = sign_task(self.task, self.rector)

        # Corrupt the signature value
        sig.signature_value = base64.b64encode(b'corrupted_signature_value_for_testing').decode('utf-8')
        sig.save()

        res = verify_signature(sig.verification_id)
        self.assertFalse(res['is_valid'])
        self.assertEqual(res['status'], 'INVALID')

    def test_unknown_verification_id_returns_not_found(self):
        """Querying an unknown verification ID returns not found status."""
        res = verify_signature('SIG-NON-EXISTENT')
        self.assertFalse(res['is_valid'])
        self.assertEqual(res['status'], 'NOT_FOUND')

    # =======================================================================
    # 4. REVOCATION WORKFLOW TESTS
    # =======================================================================

    def test_rector_and_superadmin_can_revoke_signature(self):
        """Superadmin or Rector can revoke an electronic signature with mandatory reason."""
        sig = sign_task(self.task, self.rector)

        self.assertTrue(can_revoke_signature(self.rector, sig))
        self.assertTrue(can_revoke_signature(self.superadmin, sig))
        self.assertFalse(can_revoke_signature(self.employee, sig))
        self.assertFalse(can_revoke_signature(self.dept_head, sig))

        revoked_sig = revoke_signature(sig, self.rector, reason='Administrative protocol update')
        self.assertEqual(revoked_sig.status, ElectronicSignature.Status.REVOKED)
        self.assertIsNotNone(revoked_sig.revoked_at)
        self.assertEqual(revoked_sig.revocation_reason, 'Administrative protocol update')

        # Public verification should now return REVOKED
        res = verify_signature(sig.verification_id)
        self.assertFalse(res['is_valid'])
        self.assertEqual(res['status'], 'REVOKED')

    def test_revocation_requires_mandatory_reason(self):
        """Revoking without reason raises ValidationError."""
        sig = sign_task(self.task, self.rector)
        with self.assertRaises(ValidationError):
            revoke_signature(sig, self.rector, reason='')

    # =======================================================================
    # 5. PUBLIC VERIFICATION PRIVACY & ENDPOINT TESTS
    # =======================================================================

    def test_public_verification_page_requires_no_login(self):
        """Public verification endpoint is accessible without authentication."""
        sig = sign_task(self.task, self.rector)
        client = Client()

        url = reverse('public_verify', kwargs={'verification_id': sig.verification_id})
        response = client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'VALID SIGNATURE')
        self.assertContains(response, sig.verification_id)
        self.assertContains(response, self.task.task_number)
        self.assertContains(response, self.rector.display_name)

        # Ensure NO sensitive private details are exposed
        self.assertNotContains(response, 'salary')
        self.assertNotContains(response, '000 000 UZS')
        self.assertNotContains(response, 'phone')
        self.assertNotContains(response, 'emp@univ.test')

    def test_public_qr_code_endpoint(self):
        """QR code image endpoint returns valid PNG binary stream."""
        sig = sign_task(self.task, self.rector)
        client = Client()

        url = reverse('signature_qr', kwargs={'verification_id': sig.verification_id})
        response = client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertGreater(len(response.content), 100)

    # =======================================================================
    # 6. KEY ROTATION TESTS
    # =======================================================================

    def test_key_rotation_historical_signature_remains_verifiable(self):
        """
        Signatures created with key version 1 remain verifiable even when a new active key exists.
        """
        # Create key version 1
        key_v1 = ed25519.Ed25519PrivateKey.generate()
        SignatureKeyProvider.register_versioned_key('v1', key_v1)

        sig = sign_task(self.task, self.rector)
        self.assertEqual(sig.key_version, 'v1')

        # Rotate to key version 2
        key_v2 = ed25519.Ed25519PrivateKey.generate()
        SignatureKeyProvider.register_versioned_key('v2', key_v2)

        # Historical signature created under v1 must still verify cleanly
        res = verify_signature(sig.verification_id)
        self.assertTrue(res['is_valid'])
        self.assertEqual(res['status'], 'VALID')

    # =======================================================================
    # 7. AUDIT LOG & NOTIFICATION TESTS
    # =======================================================================

    def test_audit_logs_and_notifications_created_on_signing(self):
        """Signing generates SIGNATURE_CREATED audit log and notifications for assignees."""
        Notification.objects.all().delete()
        AuditLog.objects.all().delete()

        sig = sign_task(self.task, self.rector)

        # Verify Audit Log
        audit = AuditLog.objects.filter(action=AuditLog.Actions.SIGNATURE_CREATED).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.rector)
        self.assertEqual(audit.details['verification_id'], sig.verification_id)

        # Verify Notification dispatched to assigned employee
        notif = Notification.objects.filter(recipient=self.employee).first()
        self.assertIsNotNone(notif)
        self.assertIn(sig.verification_id, notif.message)
