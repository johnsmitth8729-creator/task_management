from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from operations.models import (
    DocumentVersion,
    RequestApprovalStep,
    RequestCategory,
    RequestType,
    UniversityDocument,
    UniversityRequest,
)
from operations.services import (
    DocumentService,
    RequestWorkflowEngine,
)
from organization.models import Department, Position

User = get_user_model()


class RequestWorkflowEngineTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='Computer Science', code='CS_DEPT')
        self.dept_head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Dept Head')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.employee_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.dept_head = User.objects.create_user(
            username='dept_head_user',
            email='head@uni.edu',
            password='Password123!',
            department=self.dept,
        )
        self.dept_head.roles.add(self.dept_head_role)
        self.dept.head = self.dept_head
        self.dept.save()

        self.rector = User.objects.create_user(
            username='rector_user',
            email='rector@uni.edu',
            password='Password123!',
        )
        self.rector.roles.add(self.rector_role)

        self.employee = User.objects.create_user(
            username='staff_user',
            email='staff@uni.edu',
            password='Password123!',
            department=self.dept,
        )
        self.employee.roles.add(self.employee_role)

        self.category = RequestCategory.objects.create(
            name='Academic Services',
            code=RequestCategory.CategoryCode.ACADEMIC,
        )
        self.request_type = RequestType.objects.create(
            category=self.category,
            name='Conference Attendance Grant',
            code='CONF_GRANT',
            requires_dept_head_approval=True,
            requires_dean_or_vr_approval=False,
            requires_rector_approval=True,
            sla_resolution_hours=48,
        )

    def test_submit_request_and_pipeline_construction(self):
        uni_req = RequestWorkflowEngine.submit_request(
            request_type=self.request_type,
            requester=self.employee,
            subject='IEEE Conference Presentation',
            details_payload={'city': 'Tashkent', 'budget': '5000000'},
            is_urgent=True,
        )
        self.assertEqual(uni_req.status, UniversityRequest.Status.SUBMITTED)
        self.assertEqual(uni_req.current_step_number, 1)
        self.assertTrue(uni_req.is_urgent)

        steps = uni_req.approval_steps.all().order_by('step_number')
        self.assertEqual(steps.count(), 2)
        # Step 1: Dept Head
        self.assertEqual(steps[0].approver_role, RequestApprovalStep.ApproverRole.DEPARTMENT_HEAD)
        self.assertEqual(steps[0].assigned_approver, self.dept_head)
        self.assertEqual(steps[0].status, RequestApprovalStep.StepStatus.PENDING)
        # Step 2: Rector
        self.assertEqual(steps[1].approver_role, RequestApprovalStep.ApproverRole.RECTOR)
        self.assertEqual(steps[1].status, RequestApprovalStep.StepStatus.PENDING)

    def test_approval_step_progression_to_completion(self):
        uni_req = RequestWorkflowEngine.submit_request(
            request_type=self.request_type,
            requester=self.employee,
            subject='Curriculum Update 2026',
        )
        step1 = uni_req.approval_steps.get(step_number=1)
        step2 = uni_req.approval_steps.get(step_number=2)

        # 1. Dept Head approves Step 1
        ok = RequestWorkflowEngine.process_approval_step(
            step=step1,
            user=self.dept_head,
            decision='APPROVED',
            comments='Strong academic justification.'
        )
        self.assertTrue(ok)
        uni_req.refresh_from_db()
        step1.refresh_from_db()
        self.assertEqual(step1.status, RequestApprovalStep.StepStatus.APPROVED)
        self.assertEqual(uni_req.current_step_number, 2)
        self.assertEqual(uni_req.status, UniversityRequest.Status.IN_REVIEW)

        # 2. Rector approves Step 2 (Final Step)
        ok2 = RequestWorkflowEngine.process_approval_step(
            step=step2,
            user=self.rector,
            decision='APPROVED',
            comments='Approved by University Council.'
        )
        self.assertTrue(ok2)
        uni_req.refresh_from_db()
        step2.refresh_from_db()
        self.assertEqual(step2.status, RequestApprovalStep.StepStatus.APPROVED)
        self.assertEqual(uni_req.status, UniversityRequest.Status.APPROVED)
        self.assertIsNotNone(uni_req.resolved_at)

    def test_rejection_marks_subsequent_steps_skipped(self):
        uni_req = RequestWorkflowEngine.submit_request(
            request_type=self.request_type,
            requester=self.employee,
            subject='International Travel Application',
        )
        step1 = uni_req.approval_steps.get(step_number=1)
        step2 = uni_req.approval_steps.get(step_number=2)

        # Dept Head Rejects
        RequestWorkflowEngine.process_approval_step(
            step=step1,
            user=self.dept_head,
            decision='REJECTED',
            comments='Department funding quota exceeded.'
        )
        uni_req.refresh_from_db()
        step1.refresh_from_db()
        step2.refresh_from_db()

        self.assertEqual(uni_req.status, UniversityRequest.Status.REJECTED)
        self.assertEqual(step1.status, RequestApprovalStep.StepStatus.REJECTED)
        self.assertEqual(step2.status, RequestApprovalStep.StepStatus.SKIPPED)

    def test_requester_cancellation(self):
        uni_req = RequestWorkflowEngine.submit_request(
            request_type=self.request_type,
            requester=self.employee,
            subject='Accidental Duplicate Submission',
        )
        cancelled = RequestWorkflowEngine.cancel_request(uni_req, self.employee)
        self.assertTrue(cancelled)
        uni_req.refresh_from_db()
        self.assertEqual(uni_req.status, UniversityRequest.Status.CANCELLED)


class DocumentRegistryTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            username='admin_docs',
            email='admin_docs@uni.edu',
            password='Password123!',
        )
        self.test_file_v1 = SimpleUploadedFile("order_101.pdf", b"Official Order v1 content", content_type="application/pdf")
        self.test_file_v2 = SimpleUploadedFile("order_101_v2.pdf", b"Official Order v2 amended content", content_type="application/pdf")

    def test_document_creation_and_versioning(self):
        doc = UniversityDocument.objects.create(
            doc_number='101-B/2026',
            title='Academic Calendar Regulation 2026/2027',
            document_type=UniversityDocument.DocumentType.ORDER_RECTOR,
            file=self.test_file_v1,
            version=1,
            created_by=self.superadmin,
        )
        self.assertEqual(doc.version, 1)

        # Upload amendment version
        v2 = DocumentService.add_version(
            document=doc,
            file=self.test_file_v2,
            changelog='Updated winter examination schedule',
            user=self.superadmin
        )
        self.assertEqual(v2.version_number, 2)
        doc.refresh_from_db()
        self.assertEqual(doc.version, 2)
        self.assertEqual(doc.versions.count(), 1)


class OperationsViewsTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='Law Faculty', code='LAW_DEPT')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Dept Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.dept_head = User.objects.create_user(
            username='law_head',
            email='law_head@uni.edu',
            password='Password123!',
            department=self.dept,
        )
        self.dept_head.roles.add(self.head_role)
        self.dept.head = self.dept_head
        self.dept.save()

        self.employee = User.objects.create_user(
            username='law_emp',
            email='law_emp@uni.edu',
            password='Password123!',
            department=self.dept,
        )
        self.employee.roles.add(self.emp_role)

        self.category = RequestCategory.objects.create(name='Legal Services', code='LEGAL')
        self.req_type = RequestType.objects.create(
            category=self.category,
            name='Contract Review',
            code='CONTRACT_REVIEW',
            requires_dept_head_approval=True,
            requires_dean_or_vr_approval=False,
        )

    def test_service_catalog_view(self):
        self.client.force_login(self.employee)
        res = self.client.get(reverse('operations:service_catalog'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Legal Services')
        self.assertContains(res, 'Contract Review')

    def test_request_submit_view(self):
        self.client.force_login(self.employee)
        res = self.client.post(reverse('operations:request_apply_direct'), {
            'request_type': str(self.req_type.id),
            'subject': 'MoU Review with Partner University',
            'is_urgent': True,
        })
        self.assertEqual(res.status_code, 302)
        self.assertTrue(UniversityRequest.objects.filter(subject='MoU Review with Partner University').exists())

    def test_approval_queue_and_decision(self):
        uni_req = RequestWorkflowEngine.submit_request(
            request_type=self.req_type,
            requester=self.employee,
            subject='Sponsorship Agreement Review',
        )
        # Dept head checks approval queue
        self.client.force_login(self.dept_head)
        res = self.client.get(reverse('operations:approval_queue'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, uni_req.request_number)

        # Dept head views detail and approves
        res_detail = self.client.get(reverse('operations:request_detail', kwargs={'pk': uni_req.id}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'Official Decision')

        res_post = self.client.post(reverse('operations:request_detail', kwargs={'pk': uni_req.id}), {
            'decision': 'APPROVED',
            'comments': 'Reviewed and approved by Dean.',
        })
        self.assertEqual(res_post.status_code, 302)
        uni_req.refresh_from_db()
        self.assertEqual(uni_req.status, UniversityRequest.Status.APPROVED)
