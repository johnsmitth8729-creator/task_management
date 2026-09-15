from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from organization.models import Department, DepartmentResponsibility
from tasks.models import Task, TaskAssignment, TaskSubmission
from tasks.services import (
    accept_assignment,
    final_approve_assignment,
    final_reject_assignment,
    first_approve_assignment,
    first_reject_assignment,
    submit_assignment,
    update_assignment_progress,
)


class WorkflowTestSuite(TestCase):
    def setUp(self):
        from django.utils.translation import activate
        activate('en')

        # Roles
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.dh_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Dept Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        # Department
        self.dept_it = Department.objects.create(code='IT', name='Information Technology')

        # Users
        self.rector = User.objects.create_user(username='wf_rector', email='rector@test.com', password='Pass!12345')
        self.rector.roles.set([self.rector_role])

        self.vice_rector = User.objects.create_user(username='wf_vr', email='vr@test.com', password='Pass!12345')
        self.vice_rector.roles.set([self.vr_role])
        DepartmentResponsibility.objects.create(vice_rector=self.vice_rector, department=self.dept_it, is_active=True)

        self.head_it = User.objects.create_user(username='wf_head_it', email='head@test.com', password='Pass!12345', department=self.dept_it)
        self.head_it.roles.set([self.dh_role])
        self.dept_it.head = self.head_it
        self.dept_it.save()

        self.emp = User.objects.create_user(username='wf_emp', email='emp@test.com', password='Pass!12345', department=self.dept_it)
        self.emp.roles.set([self.emp_role])

        # Task
        self.task = Task.objects.create(
            title='Core Portal Task',
            creator=self.rector,
            responsible_department=self.dept_it,
            status=Task.Status.ASSIGNED,
            deadline=timezone.now().date() + timedelta(days=10),
        )
        self.assignment = TaskAssignment.objects.create(
            task=self.task,
            user=self.emp,
            assigned_by=self.head_it,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )

    def test_employee_dashboard_view(self):
        self.client.force_login(self.emp)
        res = self.client.get(reverse('employee_dashboard'))
        self.assertEqual(res.status_code, 200)
        # Ensure Phase 5 development badge is NOT present
        self.assertNotContains(res, 'Phase 5')
        self.assertContains(res, 'Awaiting Final Approval')

    def test_employee_second_approval_view_with_task(self):
        # Move assignment through workflow to SECOND_APPROVAL
        accept_assignment(self.emp, self.assignment)
        self.assignment.refresh_from_db()
        update_assignment_progress(self.emp, self.assignment, 100)
        self.assignment.refresh_from_db()
        submit_assignment(self.emp, self.assignment, 'Completed all work.')
        self.assignment.refresh_from_db()
        first_approve_assignment(self.head_it, self.assignment, notes='Approved by department head')

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SECOND_APPROVAL)

        self.client.force_login(self.emp)
        res = self.client.get(reverse('employee_second_approval'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Core Portal Task')
        self.assertContains(res, 'Second Approval')

    def test_dept_dashboard_view_no_phase5_badge(self):
        self.client.force_login(self.head_it)
        res = self.client.get(reverse('dept_dashboard'))
        self.assertRedirects(res, reverse('task_list'))

    def test_workflow_end_to_end_completion(self):
        accept_assignment(self.emp, self.assignment)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.IN_PROGRESS)

        update_assignment_progress(self.emp, self.assignment, 100)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.progress, 100)

        submit_assignment(self.emp, self.assignment, 'Completed deliverable')
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SUBMITTED)

        first_approve_assignment(self.head_it, self.assignment, notes='Dept head ok')
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SECOND_APPROVAL)

        final_approve_assignment(self.vice_rector, self.assignment, notes='Final executive approval')
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.APPROVED)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.COMPLETED)


class TaskWorkflowReworkAndAuthorityTests(TestCase):
    """
    Exhaustive tests covering requirements A through Z from Section 16:
    A. Employee accepts assignment
    B. Employee updates progress
    C. Employee submits V1
    D. Department Head first approves
    E. Department Head first rejects
    F. Rejected assignment can return to IN_PROGRESS
    G. Employee can submit V2
    H. V1 remains immutable
    I. V2 is created correctly
    J. Final approval works
    K. Final rejection works
    L. Final rejection allows rework
    M. Employee can submit next version after final rejection
    N. Rejection reason is mandatory
    O. Deadline extension permission
    P. Deadline extension scope
    Q. Vice Rector cannot sign unless Acting Rector
    R. Rector can sign
    S. Department Head cannot final approve
    T. Employee cannot approve
    U. Employee cannot assign
    V. Department Head cannot assign outside department
    W. Vice Rector cannot assign outside responsibility scope
    X. Rector can assign university-wide
    Y. IDOR protection
    Z. AuditLog/TaskHistory created correctly
    """
    def setUp(self):
        from django.utils.translation import activate
        activate('en')

        self.role_rector, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.role_vr, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.role_dh, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Dept Head'})
        self.role_emp, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.dept_it = Department.objects.create(code='IT_DEPT', name='Information Technology')
        self.dept_fin = Department.objects.create(code='FIN_DEPT', name='Finance Department')

        self.rector = User.objects.create_user(username='wf_rector_z', email='rector_z@univ.uz', password='Password123!')
        self.rector.roles.add(self.role_rector)

        self.vr = User.objects.create_user(username='wf_vr_z', email='vr_z@univ.uz', password='Password123!')
        self.vr.roles.add(self.role_vr)
        DepartmentResponsibility.objects.create(vice_rector=self.vr, department=self.dept_it, is_active=True)

        self.head_it = User.objects.create_user(username='wf_head_it_z', email='head_it_z@univ.uz', password='Password123!', department=self.dept_it)
        self.head_it.roles.add(self.role_dh)
        self.dept_it.head = self.head_it
        self.dept_it.save()

        self.head_fin = User.objects.create_user(username='wf_head_fin_z', email='head_fin_z@univ.uz', password='Password123!', department=self.dept_fin)
        self.head_fin.roles.add(self.role_dh)
        self.dept_fin.head = self.head_fin
        self.dept_fin.save()

        self.emp_it = User.objects.create_user(username='wf_emp_it_z', email='emp_it_z@univ.uz', password='Password123!', department=self.dept_it)
        self.emp_it.roles.add(self.role_emp)

        self.emp_fin = User.objects.create_user(username='wf_emp_fin_z', email='emp_fin_z@univ.uz', password='Password123!', department=self.dept_fin)
        self.emp_fin.roles.add(self.role_emp)

        self.task_it = Task.objects.create(
            title='IT Infrastructure Project',
            creator=self.rector,
            responsible_department=self.dept_it,
            status=Task.Status.ASSIGNED,
            deadline=timezone.now().date() + timedelta(days=15),
        )
        self.assign_it = TaskAssignment.objects.create(
            task=self.task_it,
            user=self.emp_it,
            assigned_by=self.head_it,
            is_primary=True,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )

        self.task_fin = Task.objects.create(
            title='Annual Financial Audit',
            creator=self.rector,
            responsible_department=self.dept_fin,
            status=Task.Status.ASSIGNED,
            deadline=timezone.now().date() + timedelta(days=20),
        )
        self.assign_fin = TaskAssignment.objects.create(
            task=self.task_fin,
            user=self.emp_fin,
            assigned_by=self.head_fin,
            is_primary=True,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )

    # A. Employee accepts assignment
    def test_A_employee_accepts_assignment(self):
        accept_assignment(self.emp_it, self.assign_it)
        self.assign_it.refresh_from_db()
        self.task_it.refresh_from_db()
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.IN_PROGRESS)
        self.assertEqual(self.task_it.status, Task.Status.IN_PROGRESS)

    # B. Employee updates progress
    def test_B_employee_updates_progress(self):
        accept_assignment(self.emp_it, self.assign_it)
        update_assignment_progress(self.emp_it, self.assign_it, 65)
        self.assign_it.refresh_from_db()
        self.task_it.refresh_from_db()
        self.assertEqual(self.assign_it.progress, 65)
        self.assertEqual(self.task_it.progress, 65)

    # C. Employee submits V1
    def test_C_employee_submits_v1(self):
        accept_assignment(self.emp_it, self.assign_it)
        sub1 = submit_assignment(self.emp_it, self.assign_it, 'V1: Initial deliverables completed.')
        self.assign_it.refresh_from_db()
        self.assertEqual(sub1.version, 1)
        self.assertEqual(sub1.status, TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL)
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.SUBMITTED)
        self.assertEqual(self.assign_it.progress, 100)

    # D. Department Head first approves
    def test_D_department_head_first_approves(self):
        accept_assignment(self.emp_it, self.assign_it)
        sub1 = submit_assignment(self.emp_it, self.assign_it, 'V1 deliverables')
        appr = first_approve_assignment(self.head_it, self.assign_it, notes='Quality looks good.')
        self.assign_it.refresh_from_db()
        sub1.refresh_from_db()
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.SECOND_APPROVAL)
        self.assertEqual(sub1.status, TaskSubmission.SubmissionStatus.FIRST_APPROVED)
        self.assertEqual(appr.stage, 'FIRST_APPROVAL')
        self.assertEqual(appr.decision, 'APPROVED')

    # E. Department Head first rejects
    def test_E_department_head_first_rejects(self):
        accept_assignment(self.emp_it, self.assign_it)
        sub1 = submit_assignment(self.emp_it, self.assign_it, 'V1 deliverables')
        rej = first_reject_assignment(self.head_it, self.assign_it, reason='Incomplete test coverage.')
        self.assign_it.refresh_from_db()
        sub1.refresh_from_db()
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.REJECTED)
        self.assertEqual(sub1.status, TaskSubmission.SubmissionStatus.FIRST_REJECTED)
        self.assertEqual(rej.stage, 'FIRST_APPROVAL')
        self.assertEqual(rej.decision, 'REJECTED')
        self.assertEqual(rej.reason, 'Incomplete test coverage.')

    # F. Rejected assignment can return to IN_PROGRESS
    def test_F_rejected_assignment_can_return_to_in_progress(self):
        from tasks.permissions import can_start_rework
        from tasks.services import start_rework
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'V1 deliverables')
        first_reject_assignment(self.head_it, self.assign_it, reason='Needs improvement.')
        self.assign_it.refresh_from_db()

        self.assertTrue(can_start_rework(self.emp_it, self.assign_it))
        start_rework(self.emp_it, self.assign_it)
        self.assign_it.refresh_from_db()
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.IN_PROGRESS)

    # G. Employee can submit V2
    def test_G_employee_can_submit_v2(self):
        from tasks.services import start_rework
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'V1 initial')
        first_reject_assignment(self.head_it, self.assign_it, reason='Needs revision.')
        self.assign_it.refresh_from_db()

        start_rework(self.emp_it, self.assign_it)
        self.assign_it.refresh_from_db()
        sub2 = submit_assignment(self.emp_it, self.assign_it, 'V2 revised deliverables.')
        self.assign_it.refresh_from_db()
        self.assertEqual(sub2.version, 2)
        self.assertEqual(sub2.status, TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL)
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.SUBMITTED)

    # H. V1 remains immutable
    def test_H_v1_remains_immutable(self):
        from tasks.services import start_rework
        accept_assignment(self.emp_it, self.assign_it)
        sub1 = submit_assignment(self.emp_it, self.assign_it, 'V1 initial work')
        first_reject_assignment(self.head_it, self.assign_it, reason='Needs more analysis.')
        self.assign_it.refresh_from_db()

        start_rework(self.emp_it, self.assign_it)
        self.assign_it.refresh_from_db()
        sub2 = submit_assignment(self.emp_it, self.assign_it, 'V2 revised work')

        sub1.refresh_from_db()
        self.assertEqual(sub1.version, 1)
        self.assertEqual(sub1.status, TaskSubmission.SubmissionStatus.FIRST_REJECTED)
        self.assertEqual(sub1.submission_text, 'V1 initial work')

    # I. V2 is created correctly
    def test_I_v2_is_created_correctly(self):
        from tasks.services import start_rework
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'V1 text')
        first_reject_assignment(self.head_it, self.assign_it, reason='Reject V1')
        self.assign_it.refresh_from_db()

        start_rework(self.emp_it, self.assign_it)
        self.assign_it.refresh_from_db()
        sub2 = submit_assignment(self.emp_it, self.assign_it, 'V2 text')

        submissions = list(TaskSubmission.objects.filter(assignment=self.assign_it).order_by('version'))
        self.assertEqual(len(submissions), 2)
        self.assertEqual(submissions[0].version, 1)
        self.assertEqual(submissions[1].version, 2)
        self.assertEqual(submissions[1].submission_text, 'V2 text')

    # J. Final approval works
    def test_J_final_approval_works(self):
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable ready')
        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()

        appr = final_approve_assignment(self.vr, self.assign_it, notes='Executive approved')
        self.assign_it.refresh_from_db()
        self.task_it.refresh_from_db()
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.APPROVED)
        self.assertEqual(self.task_it.status, Task.Status.COMPLETED)
        self.assertEqual(self.task_it.progress, 100)
        self.assertIsNotNone(self.task_it.completed_at)
        self.assertEqual(appr.stage, 'FINAL_APPROVAL')
        self.assertEqual(appr.decision, 'APPROVED')

    # K. Final rejection works
    def test_K_final_rejection_works(self):
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable')
        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()

        rej = final_reject_assignment(self.rector, self.assign_it, reason='Executive standards not met.')
        self.assign_it.refresh_from_db()
        sub = TaskSubmission.objects.filter(assignment=self.assign_it).order_by('-version').first()
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.REJECTED)
        self.assertEqual(sub.status, TaskSubmission.SubmissionStatus.FINAL_REJECTED)
        self.assertEqual(rej.stage, 'SECOND_APPROVAL')
        self.assertEqual(rej.decision, 'REJECTED')
        self.assertEqual(rej.reason, 'Executive standards not met.')

    # L. Final rejection allows rework
    def test_L_final_rejection_allows_rework(self):
        from tasks.permissions import can_start_rework
        from tasks.services import start_rework
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable')
        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()
        final_reject_assignment(self.rector, self.assign_it, reason='Executive rework needed.')
        self.assign_it.refresh_from_db()

        self.assertTrue(can_start_rework(self.emp_it, self.assign_it))
        start_rework(self.emp_it, self.assign_it)
        self.assign_it.refresh_from_db()
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.IN_PROGRESS)

    # M. Employee can submit next version after final rejection
    def test_M_employee_can_submit_next_version_after_final_rejection(self):
        from tasks.services import start_rework
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'V1 work')
        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()
        final_reject_assignment(self.rector, self.assign_it, reason='Executive rework needed.')
        self.assign_it.refresh_from_db()

        start_rework(self.emp_it, self.assign_it)
        self.assign_it.refresh_from_db()
        sub2 = submit_assignment(self.emp_it, self.assign_it, 'V2 addressed executive feedback.')
        self.assign_it.refresh_from_db()
        self.assertEqual(sub2.version, 2)
        self.assertEqual(sub2.status, TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL)
        self.assertEqual(self.assign_it.assignment_status, TaskAssignment.AssignmentStatus.SUBMITTED)

    # N. Rejection reason is mandatory
    def test_N_rejection_reason_is_mandatory(self):
        from django.core.exceptions import ValidationError
        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable')
        self.assign_it.refresh_from_db()

        # First reject with empty reason -> error
        with self.assertRaises(ValidationError):
            first_reject_assignment(self.head_it, self.assign_it, reason='   ')

        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()

        # Final reject with empty reason -> error
        with self.assertRaises(ValidationError):
            final_reject_assignment(self.rector, self.assign_it, reason='')

    # O. Deadline extension permission
    def test_O_deadline_extension_permission(self):
        from tasks.permissions import can_extend_task_deadline
        self.assertTrue(can_extend_task_deadline(self.rector, self.task_it))
        self.assertTrue(can_extend_task_deadline(self.vr, self.task_it))
        self.assertFalse(can_extend_task_deadline(self.head_it, self.task_it))
        self.assertFalse(can_extend_task_deadline(self.emp_it, self.task_it))

    # P. Deadline extension scope
    def test_P_deadline_extension_scope(self):
        from django.core.exceptions import ValidationError
        from tasks.permissions import can_extend_task_deadline
        from tasks.services import extend_task_deadline

        # VR has responsibility for IT, not Finance
        self.assertFalse(can_extend_task_deadline(self.vr, self.task_fin))
        with self.assertRaises(ValidationError):
            extend_task_deadline(self.vr, self.task_fin, self.task_fin.deadline + timedelta(days=5), reason='VR test')

        # Rector has university-wide authority over Finance
        self.assertTrue(can_extend_task_deadline(self.rector, self.task_fin))
        new_dl = self.task_fin.deadline + timedelta(days=5)
        ext = extend_task_deadline(self.rector, self.task_fin, new_dl, reason='Extended by Rector.')
        self.task_fin.refresh_from_db()
        self.assertEqual(self.task_fin.deadline, new_dl)
        self.assertIsNotNone(ext)

    # Q. Vice Rector cannot sign unless Acting Rector
    def test_Q_vice_rector_cannot_sign_unless_acting_rector(self):
        from organization.services import assign_acting_rector, revoke_acting_rector
        from signatures.permissions import can_sign_task

        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable')
        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()
        final_approve_assignment(self.rector, self.assign_it, notes='Rector approved')
        self.task_it.refresh_from_db()

        # Regular Vice Rector is strictly denied
        allowed, reason = can_sign_task(self.vr, self.task_it)
        self.assertFalse(allowed)
        self.assertIn('Vice Rectors are not authorized', reason)

        # Delegate Acting Rector authority to Vice Rector
        delegation = assign_acting_rector(rector=self.rector, acting_rector=self.vr, actor=self.rector)
        self.vr.refresh_from_db()
        self.assertTrue(self.vr.can_act_as_rector)

        # Now Acting Rector has signing authority
        allowed, reason = can_sign_task(self.vr, self.task_it)
        self.assertTrue(allowed)

        # Revoke Acting Rector delegation
        revoke_acting_rector(delegation, actor=self.rector)
        self.vr.refresh_from_db()
        allowed_after_revoke, _ = can_sign_task(self.vr, self.task_it)
        self.assertFalse(allowed_after_revoke)

    # R. Rector can sign
    def test_R_rector_can_sign(self):
        from signatures.permissions import can_sign_task
        from signatures.services import sign_task

        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable')
        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()
        final_approve_assignment(self.rector, self.assign_it, notes='Rector approved')
        self.task_it.refresh_from_db()

        allowed, _ = can_sign_task(self.rector, self.task_it)
        self.assertTrue(allowed)

        sig = sign_task(task=self.task_it, signer=self.rector)
        self.assertEqual(sig.status, 'SIGNED')
        self.assertTrue(sig.is_valid)

    # S. Department Head cannot final approve
    def test_S_department_head_cannot_final_approve(self):
        from django.core.exceptions import ValidationError
        from tasks.permissions import can_final_approve_assignment

        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable')
        first_approve_assignment(self.head_it, self.assign_it, notes='Head ok')
        self.assign_it.refresh_from_db()

        self.assertFalse(can_final_approve_assignment(self.head_it, self.assign_it))
        with self.assertRaises(ValidationError):
            final_approve_assignment(self.head_it, self.assign_it, notes='DH try final approve')

    # T. Employee cannot approve
    def test_T_employee_cannot_approve(self):
        from django.core.exceptions import ValidationError
        from tasks.permissions import can_final_approve_assignment, can_first_approve_assignment

        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Deliverable')
        self.assign_it.refresh_from_db()

        self.assertFalse(can_first_approve_assignment(self.emp_it, self.assign_it))
        self.assertFalse(can_final_approve_assignment(self.emp_it, self.assign_it))

        with self.assertRaises(ValidationError):
            first_approve_assignment(self.emp_it, self.assign_it, notes='Emp try approve')

    # U. Employee cannot assign
    def test_U_employee_cannot_assign(self):
        from tasks.permissions import can_assign_employees_to_task, can_assign_task
        self.assertFalse(can_assign_task(self.emp_it, self.task_it))
        self.assertFalse(can_assign_employees_to_task(self.emp_it, self.task_it))

    # V. Department Head cannot assign outside department
    def test_V_department_head_cannot_assign_outside_department(self):
        from tasks.permissions import can_assign_employees_to_task
        self.assertTrue(can_assign_employees_to_task(self.head_it, self.task_it))
        self.assertFalse(can_assign_employees_to_task(self.head_it, self.task_fin))

    # W. Vice Rector cannot assign outside responsibility scope
    def test_W_vice_rector_cannot_assign_outside_responsibility_scope(self):
        from tasks.permissions import can_assign_employees_to_task
        self.assertTrue(can_assign_employees_to_task(self.vr, self.task_it))
        self.assertFalse(can_assign_employees_to_task(self.vr, self.task_fin))

    # X. Rector can assign university-wide
    def test_X_rector_can_assign_university_wide(self):
        from tasks.permissions import can_assign_employees_to_task, can_assign_task
        self.assertTrue(can_assign_task(self.rector, self.task_it))
        self.assertTrue(can_assign_task(self.rector, self.task_fin))
        self.assertTrue(can_assign_employees_to_task(self.rector, self.task_it))
        self.assertTrue(can_assign_employees_to_task(self.rector, self.task_fin))

    # Y. IDOR protection
    def test_Y_idor_protection(self):
        # emp_fin cannot view IT assignment detail
        self.client.force_login(self.emp_fin)
        res = self.client.get(reverse('assignment_detail', kwargs={'pk': self.assign_it.pk}))
        self.assertEqual(res.status_code, 403)

        # emp_it can view own assignment detail
        self.client.force_login(self.emp_it)
        res_ok = self.client.get(reverse('assignment_detail', kwargs={'pk': self.assign_it.pk}))
        self.assertEqual(res_ok.status_code, 200)

    # Z. AuditLog/TaskHistory created correctly
    def test_Z_audit_log_and_task_history_created_correctly(self):
        from core.models import AuditLog
        from tasks.models import TaskHistory
        from tasks.services import start_rework

        accept_assignment(self.emp_it, self.assign_it)
        submit_assignment(self.emp_it, self.assign_it, 'Initial sub')
        first_reject_assignment(self.head_it, self.assign_it, reason='Audit test reject.')
        self.assign_it.refresh_from_db()

        start_rework(self.emp_it, self.assign_it)

        # Verify TaskHistory has TASK_REWORK_STARTED
        rework_hist = TaskHistory.objects.filter(
            task=self.task_it,
            event_type=TaskHistory.EventType.TASK_REWORK_STARTED,
        ).first()
        self.assertIsNotNone(rework_hist)
        self.assertEqual(rework_hist.actor, self.emp_it)

        # Verify AuditLog has TASK_REWORK_STARTED
        rework_audit = AuditLog.objects.filter(
            action=AuditLog.Actions.TASK_REWORK_STARTED,
            actor=self.emp_it,
        ).first()
        self.assertIsNotNone(rework_audit)


