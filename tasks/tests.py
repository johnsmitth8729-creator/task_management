import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from accounts.models import Role
from core.models import Notification
from organization.models import Department, DepartmentResponsibility, Position
from organization.services import (
    assign_acting_rector,
    assign_department_head,
    assign_vice_rector_responsibility,
    revoke_acting_rector,
)
from signatures.models import ElectronicSignature
from signatures.services import sign_task
from tasks.models import (
    SubTask,
    Task,
    TaskApproval,
    TaskAssignment,
    TaskDeadlineExtension,
    TaskDependency,
    TaskHistory,
    TaskNote,
    TaskSubmission,
    TaskTemplate,
    TaskType,
)
from tasks.services import (
    accept_assignment,
    add_dependency,
    add_task_note,
    archive_task,
    assign_task,
    cancel_task,
    create_subtask,
    create_task,
    extend_task_deadline,
    final_approve_assignment,
    final_reject_assignment,
    first_approve_assignment,
    first_reject_assignment,
    get_scoped_tasks,
    submit_assignment,
    transition_status,
    unassign_user,
    update_assignment_progress,
    update_task,
)

User = get_user_model()


class TaskModelTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='IT Dept', code='IT')
        self.tt = TaskType.objects.create(name='Web Dev', code='WEB_DEV')
        self.user = User.objects.create_user(username='creator', email='c@test.com', password='Password123!')

    def test_task_creation_and_task_number_generation(self):
        task = Task.objects.create(
            title='Sample Task',
            description='Sample description',
            creator=self.user,
            responsible_department=self.dept,
            task_type=self.tt,
            priority=Task.Priority.HIGH,
            complexity=Task.Complexity.COMPLEX,
            status=Task.Status.CREATED,
        )
        self.assertIsInstance(task.id, uuid.UUID)
        self.assertTrue(task.task_number.startswith('TM-'))
        self.assertEqual(task.progress, 0)
        self.assertFalse(task.is_overdue)

    def test_is_overdue_derived_property(self):
        today = timezone.now().date()
        # Task with future deadline -> not overdue
        task_future = Task.objects.create(
            title='Future Task',
            creator=self.user,
            deadline=today + timedelta(days=5),
            status=Task.Status.IN_PROGRESS,
        )
        self.assertFalse(task_future.is_overdue)

        # Task with past deadline in IN_PROGRESS -> overdue
        task_past = Task.objects.create(
            title='Past Task',
            creator=self.user,
            deadline=today - timedelta(days=2),
            status=Task.Status.IN_PROGRESS,
        )
        self.assertTrue(task_past.is_overdue)

        # Completed task with past deadline -> not overdue
        task_completed = Task.objects.create(
            title='Completed Past Task',
            creator=self.user,
            deadline=today - timedelta(days=2),
            status=Task.Status.COMPLETED,
        )
        self.assertFalse(task_completed.is_overdue)


class TaskAssignmentTests(TestCase):
    def setUp(self):
        self.dept_it = Department.objects.create(name='IT Dept', code='IT')
        self.dept_fin = Department.objects.create(name='Finance Dept', code='FIN')
        self.rector = User.objects.create_user(username='rector', email='r@test.com', password='Password123!', is_superuser=True)
        self.emp1 = User.objects.create_user(username='emp1', email='e1@test.com', password='Password123!', department=self.dept_it)
        self.emp2 = User.objects.create_user(username='emp2', email='e2@test.com', password='Password123!', department=self.dept_it)
        self.emp_fin = User.objects.create_user(username='emp_fin', email='efin@test.com', password='Password123!', department=self.dept_fin)
        self.head_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.head_it = User.objects.create_user(username='head_it', email='hit@test.com', password='Password123!', department=self.dept_it)
        self.head_it.roles.add(self.head_role)
        self.dept_it.head = self.head_it
        self.dept_it.save()
        self.task = Task.objects.create(
            title='IT Task',
            creator=self.rector,
            responsible_department=self.dept_it,
            status=Task.Status.CREATED,
        )

    def test_assign_multiple_employees_and_primary(self):
        assignments = assign_task(self.rector, self.task, [self.emp1, self.emp2], primary_user=self.emp1)
        self.assertEqual(len(assignments), 2)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.ASSIGNED)
        self.assertEqual(self.task.primary_assignee, self.emp1)
        self.assertIn(self.emp2, self.task.assignees)

    def test_assignee_must_belong_to_responsible_department(self):
        # Department Head cannot assign employee from another department
        with self.assertRaises(ValidationError):
            assign_task(self.head_it, self.task, [self.emp_fin])

        # Rector CAN assign cross-department employee and secondary_departments is updated
        assign_task(self.rector, self.task, [self.emp_fin])
        self.assertIn(self.dept_fin, self.task.secondary_departments.all())

    def test_unassign_user_and_status_reversion(self):
        assignments = assign_task(self.rector, self.task, [self.emp1], primary_user=self.emp1)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.ASSIGNED)

        unassign_user(self.rector, self.task, assignments[0])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.CREATED)
        self.assertEqual(self.task.assignments.count(), 0)


class SubTaskAndDependencyTests(TestCase):
    def setUp(self):
        self.rector = User.objects.create_user(username='rector', email='r@test.com', password='Password123!', is_superuser=True)
        self.task1 = Task.objects.create(title='Task 1', creator=self.rector)
        self.task2 = Task.objects.create(title='Task 2', creator=self.rector)

    def test_subtask_creation(self):
        st = create_subtask(self.rector, self.task1, title='Subtask 1', description='Sub desc', progress=50)
        self.assertEqual(st.parent_task, self.task1)
        self.assertEqual(st.progress, 50)
        self.assertTrue(TaskHistory.objects.filter(task=self.task1, event_type=TaskHistory.EventType.SUBTASK_CREATED).exists())

    def test_dependency_creation_and_validation(self):
        dep = add_dependency(self.rector, self.task2, self.task1)
        self.assertEqual(dep.task, self.task2)
        self.assertEqual(dep.depends_on, self.task1)

        # Self-dependency forbidden
        with self.assertRaises(ValidationError):
            add_dependency(self.rector, self.task1, self.task1)

        # Circular dependency detected
        with self.assertRaises(ValidationError):
            add_dependency(self.rector, self.task1, self.task2)


class TaskServicesAndLifecycleTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='IT', code='IT')
        self.rector = User.objects.create_user(username='rector', email='r@test.com', password='Password123!', is_superuser=True)
        self.task = create_task(
            actor=self.rector,
            title='Lifecycle Task',
            description='Test lifecycle',
            responsible_department=self.dept,
            priority=Task.Priority.URGENT,
            complexity=Task.Complexity.CRITICAL,
            status=Task.Status.CREATED,
        )

    def test_status_transitions(self):
        # CREATED -> IN_PROGRESS
        transition_status(self.rector, self.task, Task.Status.IN_PROGRESS)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.IN_PROGRESS)

        # IN_PROGRESS -> COMPLETED (automatically sets progress=100 and completed_at)
        transition_status(self.rector, self.task, Task.Status.COMPLETED)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.COMPLETED)
        self.assertEqual(self.task.progress, 100)
        self.assertIsNotNone(self.task.completed_at)

        # COMPLETED -> ARCHIVED
        archive_task(self.rector, self.task)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.ARCHIVED)
        self.assertIsNotNone(self.task.archived_at)

    def test_cancellation_requires_reason(self):
        with self.assertRaises(ValidationError):
            cancel_task(self.rector, self.task, cancellation_reason='')

        cancel_task(self.rector, self.task, cancellation_reason='Project scope changed by rectorate.')
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.CANCELLED)
        self.assertEqual(self.task.cancelled_by, self.rector)
        self.assertIsNotNone(self.task.cancelled_at)


class TaskScopingAndRBACSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.dept_it = Department.objects.create(name='IT Department', code='IT')
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN')

        self.rector = User.objects.create_user(username='rector', email='r@test.com', password='Password123!', is_superuser=True)
        self.rector.roles.add(self.rector_role)

        self.vr_acad = User.objects.create_user(username='vr.acad', email='vr@test.com', password='Password123!')
        self.vr_acad.roles.add(self.vr_role)
        assign_vice_rector_responsibility(self.vr_acad, self.dept_it, actor=self.rector)

        self.head_it = User.objects.create_user(username='head.it', email='hit@test.com', password='Password123!', department=self.dept_it)
        self.head_it.roles.add(self.head_role)
        assign_department_head(self.dept_it, self.head_it, actor=self.rector)

        self.emp_it = User.objects.create_user(username='emp.it', email='eit@test.com', password='Password123!', department=self.dept_it)
        self.emp_it.roles.add(self.emp_role)

        self.emp_fin = User.objects.create_user(username='emp.fin', email='efin@test.com', password='Password123!', department=self.dept_fin)
        self.emp_fin.roles.add(self.emp_role)

        # Tasks
        self.task_it = Task.objects.create(
            title='IT Infrastructure Setup',
            creator=self.rector,
            responsible_department=self.dept_it,
            status=Task.Status.IN_PROGRESS,
        )
        assign_task(self.rector, self.task_it, [self.emp_it], primary_user=self.emp_it)

        self.task_fin = Task.objects.create(
            title='Finance Audit Report',
            creator=self.rector,
            responsible_department=self.dept_fin,
            status=Task.Status.IN_PROGRESS,
        )
        assign_task(self.rector, self.task_fin, [self.emp_fin], primary_user=self.emp_fin)

    def test_get_scoped_tasks_per_role(self):
        # 1. Rector sees all
        rector_tasks = get_scoped_tasks(self.rector)
        self.assertIn(self.task_it, rector_tasks)
        self.assertIn(self.task_fin, rector_tasks)

        # 2. Vice Rector sees IT task, but NOT Finance task
        vr_tasks = get_scoped_tasks(self.vr_acad)
        self.assertIn(self.task_it, vr_tasks)
        self.assertNotIn(self.task_fin, vr_tasks)

        # 3. Dept Head sees own department task only
        head_tasks = get_scoped_tasks(self.head_it)
        self.assertIn(self.task_it, head_tasks)
        self.assertNotIn(self.task_fin, head_tasks)

        # 4. Employee sees only assigned task
        emp_tasks = get_scoped_tasks(self.emp_it)
        self.assertIn(self.task_it, emp_tasks)
        self.assertNotIn(self.task_fin, emp_tasks)

    def test_idor_protection_on_task_detail_and_edit(self):
        # Vice Rector accessing Finance task -> 403 Forbidden
        self.client.login(username='vr.acad', password='Password123!')
        res_vr_blocked = self.client.get(reverse('task_detail', kwargs={'pk': self.task_fin.pk}))
        self.assertEqual(res_vr_blocked.status_code, 403)

        # Department Head accessing Finance task -> 403 Forbidden
        self.client.login(username='head.it', password='Password123!')
        res_head_blocked = self.client.get(reverse('task_detail', kwargs={'pk': self.task_fin.pk}))
        self.assertEqual(res_head_blocked.status_code, 403)

        # Employee accessing task assigned to other department -> 403 Forbidden
        self.client.login(username='emp.it', password='Password123!')
        res_emp_blocked = self.client.get(reverse('task_detail', kwargs={'pk': self.task_fin.pk}))
        self.assertEqual(res_emp_blocked.status_code, 403)

        # Employee accessing assigned task -> OK 200 (follows redirect to assignment_detail)
        res_emp_ok = self.client.get(reverse('task_detail', kwargs={'pk': self.task_it.pk}), follow=True)
        self.assertEqual(res_emp_ok.status_code, 200)

        # Employee attempting to access task edit -> 403 Forbidden
        res_emp_edit_blocked = self.client.get(reverse('task_edit', kwargs={'pk': self.task_it.pk}))
        self.assertEqual(res_emp_edit_blocked.status_code, 403)


class TaskViewCRUDTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.dept = Department.objects.create(name='IT Dept', code='IT')
        self.tt = TaskType.objects.create(name='Development', code='DEV')
        self.rector = User.objects.create_user(username='rector', email='r@test.com', password='Password123!', is_superuser=True)
        self.rector.roles.add(self.rector_role)
        self.client.login(username='rector', password='Password123!')

    def test_task_list_view_and_filtering(self):
        t1 = Task.objects.create(title='Alpha Task', creator=self.rector, responsible_department=self.dept, priority=Task.Priority.HIGH)
        t2 = Task.objects.create(title='Beta Task', creator=self.rector, responsible_department=self.dept, priority=Task.Priority.LOW)

        res = self.client.get(reverse('task_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Alpha Task')
        self.assertContains(res, 'Beta Task')

        # Filter by priority
        res_filtered = self.client.get(reverse('task_list') + '?priority=HIGH')
        self.assertContains(res_filtered, 'Alpha Task')
        self.assertNotContains(res_filtered, 'Beta Task')

    def test_task_create_view_post(self):
        res = self.client.post(
            reverse('task_create'),
            {
                'title': 'New Portal Project',
                'description': 'Full redesign project',
                'responsible_department': str(self.dept.id),
                'task_type': str(self.tt.id),
                'priority': Task.Priority.URGENT,
                'complexity': Task.Complexity.CRITICAL,
                'start_date': '2026-08-25',
                'deadline': '2026-09-25',
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Task.objects.filter(title='New Portal Project').exists())

    def test_task_cancel_view_post(self):
        task = Task.objects.create(title='Task to Cancel', creator=self.rector, responsible_department=self.dept)
        res = self.client.post(
            reverse('task_cancel', kwargs={'pk': task.pk}),
            {'cancellation_reason': 'Unavoidable budget reallocation.'},
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.CANCELLED)
        self.assertEqual(task.cancellation_reason, 'Unavoidable budget reallocation.')

    def test_task_type_crud_rector_only(self):
        res = self.client.post(
            reverse('task_type_create'),
            {'name': 'Security Audit', 'code': 'SEC_AUDIT', 'description': 'Security QA', 'is_active': True},
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(TaskType.objects.filter(code='SEC_AUDIT').exists())

    def test_task_archive_view_post_backend_security(self):
        task = Task.objects.create(
            title='Task to Archive',
            creator=self.rector,
            responsible_department=self.dept,
            status=Task.Status.COMPLETED,
        )
        res = self.client.post(
            reverse('task_archive', kwargs={'pk': task.pk}),
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.ARCHIVED)


class LanguageAndThemeUITests(TestCase):
    def setUp(self):
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.user = User.objects.create_user(
            username='admin_ui',
            email='admin_ui@test.com',
            password='Password123!',
            first_name='Admin',
            last_name='User',
        )
        self.user.roles.add(self.rector_role)
        self.client = Client()
        self.client.force_login(self.user)

    def test_language_switch_to_uzbek(self):
        # Post to standard Django set_language endpoint
        res = self.client.post(
            reverse('set_language'),
            {'language': 'uz', 'next': reverse('dashboard')},
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.cookies['django_language'].value, 'uz')

    def test_language_switch_to_english(self):
        res = self.client.post(
            reverse('set_language'),
            {'language': 'en', 'next': reverse('dashboard')},
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.cookies['django_language'].value, 'en')

    def test_navbar_and_modal_components_rendered(self):
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        # Theme toggle button
        self.assertContains(res, 'theme-toggle-btn')
        # Language switcher globe
        self.assertContains(res, 'lang-switcher-btn')
        self.assertContains(res, 'bi-globe2')
        # Reusable confirm modal
        self.assertContains(res, 'id="confirmModal"')
        # Script tags for app.js and theme check
        self.assertContains(res, 'tm_app_theme')


# ===========================================================================
# PHASE 4 — Employee Workflow Tests
# ===========================================================================

class Phase4AssignmentWorkflowTests(TestCase):
    """Core tests for Phase 4 assignment workflow: accept, progress, notes, submit."""

    def setUp(self):
        self.dept = Department.objects.create(name='IT Dept', code='IT4')
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})
        self.dept_head_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Dept Head'})
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})

        self.rector = User.objects.create_user(
            username='rector4', email='r4@test.com', password='Pass!23456',
            is_superuser=True
        )
        self.rector.roles.set([self.rector_role])

        self.employee = User.objects.create_user(
            username='emp4', email='e4@test.com', password='Pass!23456',
            department=self.dept
        )
        self.employee.roles.set([self.emp_role])

        self.dept_head = User.objects.create_user(
            username='dh4', email='dh4@test.com', password='Pass!23456',
            department=self.dept
        )
        self.dept_head.roles.set([self.dept_head_role])

        self.task = Task.objects.create(
            title='Phase 4 Test Task',
            creator=self.rector,
            responsible_department=self.dept,
            status=Task.Status.CREATED,
        )
        # Create assignment in ASSIGNED state
        self.assignment = TaskAssignment.objects.create(
            task=self.task,
            user=self.employee,
            assigned_by=self.rector,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )
        # Put task in ASSIGNED status
        self.task.status = Task.Status.ASSIGNED
        self.task.save(update_fields=['status'])

    # ------- accept_assignment -------

    def test_accept_assignment_transitions_status(self):
        """Employee accepting moves assignment ASSIGNED→IN_PROGRESS and task ASSIGNED→IN_PROGRESS."""
        result = accept_assignment(self.employee, self.assignment)
        self.assertEqual(result.assignment_status, TaskAssignment.AssignmentStatus.IN_PROGRESS)
        self.assertIsNotNone(result.accepted_at)

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.IN_PROGRESS)

    def test_accept_assignment_creates_history(self):
        accept_assignment(self.employee, self.assignment)
        self.assertTrue(
            TaskHistory.objects.filter(
                task=self.task,
                event_type=TaskHistory.EventType.TASK_ACCEPTED,
                actor=self.employee,
            ).exists()
        )

    def test_cannot_accept_other_employees_assignment(self):
        """Another employee cannot accept this assignment."""
        other = User.objects.create_user(username='other4', email='o4@test.com', password='Pass!23456')
        with self.assertRaises(Exception):
            accept_assignment(other, self.assignment)

    def test_cannot_double_accept(self):
        """Accepting twice raises ValidationError."""
        accept_assignment(self.employee, self.assignment)
        with self.assertRaises(Exception):
            accept_assignment(self.employee, self.assignment)

    # ------- update_assignment_progress -------

    def test_update_progress_stores_value(self):
        """Employee can update progress 0–100 while IN_PROGRESS."""
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        result = update_assignment_progress(self.employee, self.assignment, 65)
        self.assertEqual(result.progress, 65)

    def test_update_progress_clamps_to_100(self):
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        result = update_assignment_progress(self.employee, self.assignment, 150)
        self.assertEqual(result.progress, 100)

    def test_update_progress_creates_history(self):
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        update_assignment_progress(self.employee, self.assignment, 50)
        self.assertTrue(
            TaskHistory.objects.filter(
                task=self.task,
                event_type=TaskHistory.EventType.ASSIGNMENT_PROGRESS_UPDATED,
            ).exists()
        )

    def test_cannot_update_progress_when_assigned(self):
        """Cannot update progress while still in ASSIGNED state."""
        with self.assertRaises(Exception):
            update_assignment_progress(self.employee, self.assignment, 50)

    # ------- add_task_note -------

    def test_add_task_note_creates_note(self):
        note = add_task_note(self.employee, self.task, 'Working on it', assignment=self.assignment)
        self.assertIsInstance(note, TaskNote)
        self.assertEqual(note.author, self.employee)
        self.assertEqual(note.task, self.task)

    def test_add_task_note_empty_raises(self):
        with self.assertRaises(Exception):
            add_task_note(self.employee, self.task, '   ', assignment=self.assignment)

    def test_add_task_note_creates_history(self):
        add_task_note(self.employee, self.task, 'Progress note', assignment=self.assignment)
        self.assertTrue(
            TaskHistory.objects.filter(
                task=self.task,
                event_type=TaskHistory.EventType.TASK_NOTE_CREATED,
            ).exists()
        )

    # ------- submit_assignment -------

    def test_submit_assignment_creates_submission(self):
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        submission = submit_assignment(self.employee, self.assignment, 'Work completed.')
        self.assertIsInstance(submission, TaskSubmission)
        self.assertEqual(submission.version, 1)
        self.assertEqual(submission.status, TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL)

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SUBMITTED)

    def test_submit_assignment_empty_text_raises(self):
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        with self.assertRaises(Exception):
            submit_assignment(self.employee, self.assignment, '   ')

    def test_submit_creates_history(self):
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        submit_assignment(self.employee, self.assignment, 'Done!')
        self.assertTrue(
            TaskHistory.objects.filter(
                task=self.task,
                event_type=TaskHistory.EventType.TASK_SUBMISSION_CREATED,
            ).exists()
        )

    def test_cannot_submit_without_accepting(self):
        with self.assertRaises(Exception):
            submit_assignment(self.employee, self.assignment, 'Done without accept.')

    def test_cannot_submit_twice(self):
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        submit_assignment(self.employee, self.assignment, 'First submission.')
        self.assignment.refresh_from_db()
        with self.assertRaises(Exception):
            submit_assignment(self.employee, self.assignment, 'Second submission.')


    def test_cannot_accept_completed_or_cancelled_task(self):
        """Cannot accept assignment on completed or cancelled tasks."""
        self.task.status = Task.Status.COMPLETED
        self.task.save()
        with self.assertRaises(Exception):
            accept_assignment(self.employee, self.assignment)

    def test_cannot_submit_completed_or_cancelled_task(self):
        """Cannot submit assignment on completed or cancelled tasks."""
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        self.task.status = Task.Status.COMPLETED
        self.task.save()
        with self.assertRaises(Exception):
            submit_assignment(self.employee, self.assignment, 'Done!')

    def test_submit_sets_progress_to_100(self):
        """Submitting completed work sets assignment progress to 100%."""
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()
        update_assignment_progress(self.employee, self.assignment, 50)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.progress, 50)

        submit_assignment(self.employee, self.assignment, 'Finalizing project work.')
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.progress, 100)
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SUBMITTED)


class Phase4PermissionTests(TestCase):
    """Permission layer tests for Phase 4 assignment workflow."""

    def setUp(self):
        from tasks.permissions import (
            can_accept_assignment,
            can_update_assignment_progress,
            can_submit_assignment,
            can_add_task_note,
        )
        self.can_accept = can_accept_assignment
        self.can_progress = can_update_assignment_progress
        self.can_submit = can_submit_assignment
        self.can_note = can_add_task_note

        self.dept = Department.objects.create(name='PermIT', code='PERMIT')
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})

        self.actor = User.objects.create_user(username='perm_emp', email='pe@test.com', password='Pass!23456', department=self.dept)
        self.actor.roles.set([self.emp_role])
        self.other = User.objects.create_user(username='perm_other', email='po@test.com', password='Pass!23456', department=self.dept)
        self.other.roles.set([self.emp_role])
        self.rector = User.objects.create_user(username='perm_rec', email='pr@test.com', password='Pass!23456', is_superuser=True)
        self.rector.roles.set([self.rector_role])

        self.task = Task.objects.create(
            title='Perm Task', creator=self.rector,
            responsible_department=self.dept, status=Task.Status.ASSIGNED,
        )
        self.assignment = TaskAssignment.objects.create(
            task=self.task, user=self.actor, assigned_by=self.rector,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )

    def test_can_accept_own_assigned(self):
        self.assertTrue(self.can_accept(self.actor, self.assignment))

    def test_cannot_accept_others(self):
        self.assertFalse(self.can_accept(self.other, self.assignment))

    def test_cannot_accept_when_inprogress(self):
        self.assignment.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
        self.assignment.save()
        self.assertFalse(self.can_accept(self.actor, self.assignment))

    def test_cannot_accept_when_task_completed(self):
        self.task.status = Task.Status.COMPLETED
        self.task.save()
        self.assertFalse(self.can_accept(self.actor, self.assignment))

    def test_can_progress_own_inprogress(self):
        self.assignment.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
        self.assignment.save()
        self.assertTrue(self.can_progress(self.actor, self.assignment))

    def test_cannot_progress_when_assigned(self):
        self.assertFalse(self.can_progress(self.actor, self.assignment))

    def test_cannot_progress_when_task_completed(self):
        self.assignment.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
        self.assignment.save()
        self.task.status = Task.Status.COMPLETED
        self.task.save()
        self.assertFalse(self.can_progress(self.actor, self.assignment))

    def test_can_submit_own_inprogress(self):
        self.assignment.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
        self.assignment.save()
        self.assertTrue(self.can_submit(self.actor, self.assignment))

    def test_cannot_submit_when_assigned(self):
        self.assertFalse(self.can_submit(self.actor, self.assignment))

    def test_cannot_submit_when_task_completed(self):
        self.assignment.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
        self.assignment.save()
        self.task.status = Task.Status.COMPLETED
        self.task.save()
        self.assertFalse(self.can_submit(self.actor, self.assignment))

    def test_employee_can_add_note_to_own_task(self):
        self.assertTrue(self.can_note(self.actor, self.task))


class Phase4WorkflowUrlTests(TestCase):
    """URL accessibility tests for Phase 4 workflow views."""

    def setUp(self):
        self.client = Client()
        self.dept = Department.objects.create(name='URLDept', code='URLDT')
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})
        self.dh_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'DeptHead'})
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})

        self.employee = User.objects.create_user(
            username='urltest_emp', email='utemp@test.com', password='Pass!23456', department=self.dept
        )
        self.employee.roles.set([self.emp_role])

        self.dept_head = User.objects.create_user(
            username='urltest_dh', email='utdh@test.com', password='Pass!23456', department=self.dept
        )
        self.dept_head.roles.set([self.dh_role])
        self.dept_head.is_staff = True
        self.dept_head.save()

        self.rector = User.objects.create_user(
            username='urltest_rec', email='utrec@test.com', password='Pass!23456', is_superuser=True
        )
        self.rector.roles.set([self.rector_role])

        self.task = Task.objects.create(
            title='URL Test Task', creator=self.rector,
            responsible_department=self.dept, status=Task.Status.ASSIGNED,
        )
        self.assignment = TaskAssignment.objects.create(
            task=self.task, user=self.employee, assigned_by=self.rector,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )

    def _login_as(self, user):
        self.client.force_login(user)

    def test_employee_dashboard_accessible(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('employee_dashboard'))
        self.assertEqual(res.status_code, 200)

    def test_employee_incoming_accessible(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('employee_incoming'))
        self.assertEqual(res.status_code, 200)

    def test_employee_inprogress_accessible(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('employee_inprogress'))
        self.assertEqual(res.status_code, 200)

    def test_employee_first_approval_accessible(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('employee_first_approval'))
        self.assertEqual(res.status_code, 200)

    def test_assignment_detail_accessible_to_assignee(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('assignment_detail', kwargs={'pk': self.assignment.pk}))
        self.assertEqual(res.status_code, 200)

    def test_assignment_detail_denied_to_other_employee(self):
        other = User.objects.create_user(username='other_url', email='ouurl@test.com', password='Pass!23456')
        other.roles.set([self.emp_role])
        self._login_as(other)
        res = self.client.get(reverse('assignment_detail', kwargs={'pk': self.assignment.pk}))
        self.assertEqual(res.status_code, 403)

    def test_dept_head_dashboard_redirects_to_task_list(self):
        self._login_as(self.dept_head)
        res = self.client.get(reverse('dept_dashboard'))
        self.assertRedirects(res, reverse('task_list'), fetch_redirect_response=False)

    def test_dept_head_task_list_accessible(self):
        self._login_as(self.dept_head)
        res = self.client.get(reverse('dept_task_list'))
        self.assertEqual(res.status_code, 200)

    def test_dept_head_first_approval_accessible(self):
        self._login_as(self.dept_head)
        res = self.client.get(reverse('dept_first_approval'))
        self.assertEqual(res.status_code, 200)

    def test_unauthenticated_redirected_to_login(self):
        urls = [
            reverse('employee_dashboard'),
            reverse('employee_incoming'),
            reverse('dept_dashboard'),
            reverse('dept_first_approval'),
        ]
        for url in urls:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302, msg=f"Expected redirect for {url}")

    def test_workflow_redirect_employee(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('workflow_dashboard'))
        self.assertRedirects(res, reverse('task_list'), fetch_redirect_response=False)

    def test_workflow_redirect_dept_head(self):
        self._login_as(self.dept_head)
        res = self.client.get(reverse('workflow_dashboard'))
        self.assertRedirects(res, reverse('task_list'), fetch_redirect_response=False)

    def test_accept_assignment_via_post(self):
        self._login_as(self.employee)
        res = self.client.post(reverse('assignment_accept', kwargs={'pk': self.assignment.pk}))
        self.assertRedirects(res, reverse('assignment_detail', kwargs={'pk': self.assignment.pk}), fetch_redirect_response=False)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.IN_PROGRESS)

    def test_submit_assignment_via_post(self):
        """POST to assignment_submit creates submission and moves status to SUBMITTED."""
        # Accept first
        accept_assignment(self.employee, self.assignment)
        self.assignment.refresh_from_db()

        self._login_as(self.employee)
        res = self.client.post(
            reverse('assignment_submit', kwargs={'pk': self.assignment.pk}),
            {'submission_text': 'Detailed summary of completed tasks.'}
        )
        self.assertRedirects(res, reverse('assignment_detail', kwargs={'pk': self.assignment.pk}), fetch_redirect_response=False)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SUBMITTED)
        self.assertEqual(self.assignment.progress, 100)
        self.assertTrue(TaskSubmission.objects.filter(assignment=self.assignment).exists())

    def test_completed_task_excluded_from_incoming_and_in_progress(self):
        """Completed task assignments never appear in Incoming or In Progress lists."""
        completed_task = Task.objects.create(
            title='SpecialCompletedTaskTitle_999', creator=self.rector,
            responsible_department=self.dept, status=Task.Status.COMPLETED,
        )
        completed_assign = TaskAssignment.objects.create(
            task=completed_task, user=self.employee, assigned_by=self.rector,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )

        self._login_as(self.employee)
        res_inc = self.client.get(reverse('employee_incoming'))
        self.assertNotContains(res_inc, 'SpecialCompletedTaskTitle_999')

        completed_assign.assignment_status = TaskAssignment.AssignmentStatus.IN_PROGRESS
        completed_assign.save()
        res_prog = self.client.get(reverse('employee_inprogress'))
        self.assertNotContains(res_prog, 'SpecialCompletedTaskTitle_999')


# ===========================================================================
# PHASE 5 — WORKFLOW & SECURITY TEST SUITE
# ===========================================================================

class Phase5WorkflowServiceTests(TestCase):
    def setUp(self):
        self.rector_role = Role.objects.create(name='Rector', code=Role.Codes.RECTOR)
        self.vr_role = Role.objects.create(name='Vice Rector', code=Role.Codes.VICE_RECTOR)
        self.head_role = Role.objects.create(name='Dept Head', code=Role.Codes.DEPARTMENT_HEAD)
        self.emp_role = Role.objects.create(name='Employee', code=Role.Codes.EMPLOYEE)

        self.dept_it = Department.objects.create(name='IT Dept', code='IT_P5')
        self.dept_fin = Department.objects.create(name='Finance Dept', code='FIN_P5')

        self.rector = User.objects.create_user(username='rector_p5', email='rec_p5@test.com', password='Pass!12345')
        self.rector.roles.set([self.rector_role])

        self.vr_acad = User.objects.create_user(username='vr_acad_p5', email='vr_acad_p5@test.com', password='Pass!12345')
        self.vr_acad.roles.set([self.vr_role])
        DepartmentResponsibility.objects.create(vice_rector=self.vr_acad, department=self.dept_it)

        self.head_it = User.objects.create_user(username='head_it_p5', email='head_it_p5@test.com', password='Pass!12345', department=self.dept_it)
        self.head_it.roles.set([self.head_role])

        self.head_fin = User.objects.create_user(username='head_fin_p5', email='head_fin_p5@test.com', password='Pass!12345', department=self.dept_fin)
        self.head_fin.roles.set([self.head_role])

        self.emp_it = User.objects.create_user(username='emp_it_p5', email='emp_it_p5@test.com', password='Pass!12345', department=self.dept_it)
        self.emp_it.roles.set([self.emp_role])

        self.task = Task.objects.create(
            title='Phase 5 Workflow Task',
            creator=self.rector,
            responsible_department=self.dept_it,
            status=Task.Status.ASSIGNED,
            deadline=timezone.now().date() + timedelta(days=10),
        )
        self.assignment = TaskAssignment.objects.create(
            task=self.task,
            user=self.emp_it,
            assigned_by=self.rector,
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED,
        )

    def _setup_submitted_assignment(self):
        accept_assignment(self.emp_it, self.assignment)
        self.assignment.refresh_from_db()
        update_assignment_progress(self.emp_it, self.assignment, 100)
        sub = submit_assignment(self.emp_it, self.assignment, 'Work deliverable completed and tested.')
        self.assignment.refresh_from_db()
        return sub

    def test_first_approve_assignment_success(self):
        sub = self._setup_submitted_assignment()
        first_approve_assignment(self.head_it, self.assignment, notes='Looks good, forwarding to management.')
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SECOND_APPROVAL)

        # Check TaskApproval record
        app = TaskApproval.objects.filter(task=self.task, stage=TaskApproval.Stage.FIRST_APPROVAL).first()
        self.assertIsNotNone(app)
        self.assertEqual(app.decision, TaskApproval.Decision.APPROVED)
        self.assertEqual(app.actor, self.head_it)
        self.assertEqual(app.reason, 'Looks good, forwarding to management.')

        # Check Submission updated
        sub.refresh_from_db()
        self.assertEqual(sub.status, TaskSubmission.SubmissionStatus.FIRST_APPROVED)

    def test_first_approve_denied_to_wrong_department_head(self):
        self._setup_submitted_assignment()
        with self.assertRaises(ValidationError):
            first_approve_assignment(self.head_fin, self.assignment, notes='Illegal approval attempt')

    def test_first_approve_denied_to_employee(self):
        self._setup_submitted_assignment()
        with self.assertRaises(ValidationError):
            first_approve_assignment(self.emp_it, self.assignment)

    def test_first_reject_assignment_success(self):
        self._setup_submitted_assignment()
        first_reject_assignment(self.head_it, self.assignment, reason='Missing documentation section 3.')
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.REJECTED)

        # Check TaskApproval record
        app = TaskApproval.objects.filter(task=self.task, stage=TaskApproval.Stage.FIRST_APPROVAL).first()
        self.assertIsNotNone(app)
        self.assertEqual(app.decision, TaskApproval.Decision.REJECTED)
        self.assertEqual(app.reason, 'Missing documentation section 3.')

        # Check Notification created for employee
        notif = Notification.objects.filter(recipient=self.emp_it, notification_type=Notification.NotificationType.FIRST_APPROVAL_REJECTED).first()
        self.assertIsNotNone(notif)
        self.assertIn('rejected', notif.message.lower())

    def test_first_reject_requires_reason(self):
        self._setup_submitted_assignment()
        with self.assertRaises(ValidationError):
            first_reject_assignment(self.head_it, self.assignment, reason='   ')

    def test_final_approve_assignment_success(self):
        self._setup_submitted_assignment()
        first_approve_assignment(self.head_it, self.assignment, notes='First approval passed.')
        self.assignment.refresh_from_db()

        final_approve_assignment(self.rector, self.assignment, notes='Excellent execution, final approval granted.')
        self.assignment.refresh_from_db()
        self.task.refresh_from_db()

        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.APPROVED)
        self.assertEqual(self.task.status, Task.Status.COMPLETED)
        self.assertEqual(self.task.progress, 100)
        self.assertIsNotNone(self.task.completed_at)

        # Check TaskApproval record
        app = TaskApproval.objects.filter(task=self.task, stage=TaskApproval.Stage.FINAL_APPROVAL).first()
        self.assertIsNotNone(app)
        self.assertEqual(app.decision, TaskApproval.Decision.APPROVED)
        self.assertEqual(app.actor, self.rector)

        # Check Notification created for employee & dept head
        self.assertTrue(Notification.objects.filter(recipient=self.emp_it, notification_type=Notification.NotificationType.FINAL_APPROVED).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.head_it, notification_type=Notification.NotificationType.FINAL_APPROVED).exists())

    def test_final_approve_denied_to_department_head(self):
        self._setup_submitted_assignment()
        first_approve_assignment(self.head_it, self.assignment)
        self.assignment.refresh_from_db()

        with self.assertRaises(ValidationError):
            final_approve_assignment(self.head_it, self.assignment)

    def test_final_reject_assignment_success(self):
        self._setup_submitted_assignment()
        first_approve_assignment(self.head_it, self.assignment)
        self.assignment.refresh_from_db()

        final_reject_assignment(self.rector, self.assignment, reason='Deliverable does not meet university compliance.')
        self.assignment.refresh_from_db()
        self.task.refresh_from_db()

        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.REJECTED)
        self.assertNotEqual(self.task.status, Task.Status.COMPLETED)

        # Check TaskApproval record
        app = TaskApproval.objects.filter(task=self.task, stage=TaskApproval.Stage.SECOND_APPROVAL).first()
        self.assertIsNotNone(app)
        self.assertEqual(app.decision, TaskApproval.Decision.REJECTED)
        self.assertEqual(app.reason, 'Deliverable does not meet university compliance.')

    def test_final_reject_requires_reason(self):
        self._setup_submitted_assignment()
        first_approve_assignment(self.head_it, self.assignment)
        self.assignment.refresh_from_db()

        with self.assertRaises(ValidationError):
            final_reject_assignment(self.rector, self.assignment, reason='')

    def test_extend_task_deadline_success(self):
        old_deadline = self.task.deadline
        new_deadline = old_deadline + timedelta(days=15)

        extend_task_deadline(self.rector, self.task, new_deadline, reason='Approved project scope expansion.')
        self.task.refresh_from_db()

        self.assertEqual(self.task.deadline, new_deadline)
        ext = TaskDeadlineExtension.objects.filter(task=self.task).first()
        self.assertIsNotNone(ext)
        self.assertEqual(ext.old_deadline, old_deadline)
        self.assertEqual(ext.new_deadline, new_deadline)
        self.assertEqual(ext.extended_by, self.rector)
        self.assertEqual(ext.reason, 'Approved project scope expansion.')

    def test_extend_deadline_must_be_later_than_current(self):
        old_deadline = self.task.deadline
        with self.assertRaises(ValidationError):
            extend_task_deadline(self.rector, self.task, old_deadline - timedelta(days=1), reason='Invalid earlier date')

    def test_extend_deadline_requires_reason(self):
        new_deadline = self.task.deadline + timedelta(days=5)
        with self.assertRaises(ValidationError):
            extend_task_deadline(self.rector, self.task, new_deadline, reason='')

    def test_extend_deadline_denied_to_employee_and_dept_head(self):
        new_deadline = self.task.deadline + timedelta(days=5)
        with self.assertRaises(ValidationError):
            extend_task_deadline(self.emp_it, self.task, new_deadline, reason='Emp attempt')
        with self.assertRaises(ValidationError):
            extend_task_deadline(self.head_it, self.task, new_deadline, reason='Head attempt')


class Phase5NotificationAndSecurityViewTests(TestCase):
    def setUp(self):
        self.rector_role = Role.objects.create(name='Rector', code=Role.Codes.RECTOR)
        self.vr_role = Role.objects.create(name='Vice Rector', code=Role.Codes.VICE_RECTOR)
        self.head_role = Role.objects.create(name='Dept Head', code=Role.Codes.DEPARTMENT_HEAD)
        self.emp_role = Role.objects.create(name='Employee', code=Role.Codes.EMPLOYEE)

        self.dept = Department.objects.create(name='Academic Affairs', code='ACAD_P5')

        self.rector = User.objects.create_user(username='rector_v', email='rec_v@test.com', password='Pass!12345')
        self.rector.roles.set([self.rector_role])

        self.vr = User.objects.create_user(username='vr_v', email='vr_v@test.com', password='Pass!12345')
        self.vr.roles.set([self.vr_role])
        DepartmentResponsibility.objects.create(vice_rector=self.vr, department=self.dept)

        self.dept_head = User.objects.create_user(username='head_v', email='head_v@test.com', password='Pass!12345', department=self.dept)
        self.dept_head.roles.set([self.head_role])

        self.employee = User.objects.create_user(username='emp_v', email='emp_v@test.com', password='Pass!12345', department=self.dept)
        self.employee.roles.set([self.emp_role])

        self.task = Task.objects.create(
            title='View Test Task',
            creator=self.rector,
            responsible_department=self.dept,
            status=Task.Status.ASSIGNED,
            deadline=timezone.now().date() + timedelta(days=12),
        )
        self.assignment = TaskAssignment.objects.create(
            task=self.task,
            user=self.employee,
            assigned_by=self.rector,
            assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED,
        )
        self.submission = TaskSubmission.objects.create(
            assignment=self.assignment,
            task=self.task,
            submitted_by=self.employee,
            submission_text='Initial deliverable submission.',
            version=1,
        )

    def _login_as(self, user):
        self.client.force_login(user)

    def test_management_second_approval_accessible_to_rector_and_vr(self):
        self._login_as(self.rector)
        res = self.client.get(reverse('management_second_approval'))
        self.assertEqual(res.status_code, 200)

        self._login_as(self.vr)
        res_vr = self.client.get(reverse('management_second_approval'))
        self.assertEqual(res_vr.status_code, 200)

    def test_management_second_approval_denied_to_employee_and_head(self):
        self._login_as(self.employee)
        res_emp = self.client.get(reverse('management_second_approval'))
        self.assertEqual(res_emp.status_code, 403)

        self._login_as(self.dept_head)
        res_head = self.client.get(reverse('management_second_approval'))
        self.assertEqual(res_head.status_code, 403)

    def test_management_second_approval_detail_accessible(self):
        # Move to second approval
        first_approve_assignment(self.dept_head, self.assignment)
        self._login_as(self.rector)
        res = self.client.get(reverse('management_second_approval_detail', kwargs={'pk': self.assignment.pk}))
        self.assertEqual(res.status_code, 200)

    def test_completed_tasks_view_accessible(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('completed_tasks'))
        self.assertEqual(res.status_code, 200)

    def test_rejected_tasks_view_accessible(self):
        self._login_as(self.employee)
        res = self.client.get(reverse('rejected_tasks'))
        self.assertEqual(res.status_code, 200)

    def test_notification_list_view_and_mark_read(self):
        notif = Notification.objects.create(
            recipient=self.employee,
            notification_type=Notification.NotificationType.GENERAL,
            title='Test Alert',
            message='Test message content',
        )
        self._login_as(self.employee)
        res = self.client.get(reverse('notifications'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Test Alert')

        # Mark read via POST
        res_mark = self.client.post(reverse('notification_mark_read', kwargs={'pk': notif.pk}))
        self.assertRedirects(res_mark, reverse('notifications'), fetch_redirect_response=False)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_notification_idor_protection(self):
        notif = Notification.objects.create(
            recipient=self.employee,
            notification_type=Notification.NotificationType.GENERAL,
            title='Secret Alert',
            message='Confidential info',
        )
        other = User.objects.create_user(username='other_attacker', email='att@test.com', password='Pass!12345')
        other.roles.set([self.emp_role])

        self._login_as(other)
        res = self.client.post(reverse('notification_mark_read', kwargs={'pk': notif.pk}))
        self.assertEqual(res.status_code, 403)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)

    def test_dept_head_approve_submission_post(self):
        self._login_as(self.dept_head)
        res = self.client.post(
            reverse('dept_approve_submission', kwargs={'pk': self.submission.pk}),
            {'notes': 'Verified and approved.'}
        )
        self.assertRedirects(res, reverse('dept_first_approval'), fetch_redirect_response=False)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.SECOND_APPROVAL)

    def test_dept_head_reject_submission_post(self):
        self._login_as(self.dept_head)
        res = self.client.post(
            reverse('dept_reject_submission', kwargs={'pk': self.submission.pk}),
            {'reason': 'Incomplete calculations.'}
        )
        self.assertRedirects(res, reverse('dept_first_approval'), fetch_redirect_response=False)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.REJECTED)

    def test_management_final_approve_post(self):
        first_approve_assignment(self.dept_head, self.assignment)
        self._login_as(self.rector)
        res = self.client.post(
            reverse('management_final_approve', kwargs={'pk': self.assignment.pk}),
            {'notes': 'Final sign-off complete.'}
        )
        self.assertRedirects(res, reverse('management_second_approval_detail', kwargs={'pk': self.assignment.pk}), fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.COMPLETED)

    def test_rector_reject_submission_post(self):
        first_approve_assignment(self.dept_head, self.assignment)
        self._login_as(self.rector)
        res = self.client.post(
            reverse('management_reject', kwargs={'pk': self.assignment.pk}),
            {'reason': 'Work does not satisfy university academic requirements.'}
        )
        self.assertRedirects(res, reverse('management_second_approval'), fetch_redirect_response=False)
        self.assignment.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.REJECTED)
        self.assertNotEqual(self.task.status, Task.Status.COMPLETED)

    def test_rector_reject_completed_unsigned_task(self):
        # Even if a task status was set to COMPLETED (awaiting signature), Rector can reject it
        first_approve_assignment(self.dept_head, self.assignment)
        self.task.status = Task.Status.COMPLETED
        self.task.save()
        self._login_as(self.rector)
        res = self.client.post(
            reverse('management_reject', kwargs={'pk': self.assignment.pk}),
            {'reason': 'Deliverables failed quality check during executive signing review.'}
        )
        self.assertRedirects(res, reverse('management_second_approval'), fetch_redirect_response=False)
        self.assignment.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, TaskAssignment.AssignmentStatus.REJECTED)
        self.assertEqual(self.task.status, Task.Status.IN_PROGRESS)

    def test_task_extend_deadline_post(self):
        self._login_as(self.rector)
        new_date = (self.task.deadline + timedelta(days=20)).strftime('%Y-%m-%d')
        res = self.client.post(
            reverse('task_extend_deadline', kwargs={'pk': self.task.pk}),
            {'new_deadline': new_date, 'reason': 'University schedule adjustment.'}
        )
        self.task.refresh_from_db()
        self.assertEqual(str(self.task.deadline), new_date)


class TaskUnassignPermissionTests(TestCase):
    def setUp(self):
        from accounts.models import Role, User
        from tasks.permissions import can_unassign_user
        from tasks.services import assign_task, create_task, unassign_user

        self.rector = User.objects.create_user(username='t_rector', email='tr@u.uz', password='p')
        self.rector.roles.add(Role.objects.get_or_create(code='RECTOR')[0])

        self.dept = Department.objects.create(name='CS', code='CS_TEST')

        from organization.models import DepartmentResponsibility
        self.vr = User.objects.create_user(username='t_vr', email='tvr@u.uz', password='p')
        self.vr.roles.add(Role.objects.get_or_create(code='VICE_RECTOR')[0])
        DepartmentResponsibility.objects.create(vice_rector=self.vr, department=self.dept)

        self.dept_head = User.objects.create_user(username='t_dh', email='tdh@u.uz', password='p', department=self.dept)
        self.dept_head.roles.add(Role.objects.get_or_create(code='DEPARTMENT_HEAD')[0])
        self.dept.head = self.dept_head
        self.dept.save()

        self.emp1 = User.objects.create_user(username='t_emp1', email='te1@u.uz', password='p', department=self.dept)
        self.emp1.roles.add(Role.objects.get_or_create(code='EMPLOYEE')[0])

        self.emp2 = User.objects.create_user(username='t_emp2', email='te2@u.uz', password='p', department=self.dept)
        self.emp2.roles.add(Role.objects.get_or_create(code='EMPLOYEE')[0])

        self.emp3 = User.objects.create_user(username='t_emp3', email='te3@u.uz', password='p', department=self.dept)
        self.emp3.roles.add(Role.objects.get_or_create(code='EMPLOYEE')[0])

        self.task = create_task(
            actor=self.rector,
            title='Test Assignment Rules',
            description='Test Desc',
            responsible_department=self.dept,
        )

        # Rector assigns emp1
        self.a_emp1 = assign_task(self.rector, self.task, [self.emp1])[0]
        # Dept head assigns emp2
        self.a_emp2 = assign_task(self.dept_head, self.task, [self.emp2])[0]

    def test_assigned_employee_cannot_unassign_self(self):
        from tasks.permissions import can_unassign_user
        from tasks.services import unassign_user
        self.assertFalse(can_unassign_user(self.emp1, self.task, self.a_emp1))
        with self.assertRaises(ValidationError):
            unassign_user(self.emp1, self.task, self.a_emp1)

    def test_dept_head_cannot_unassign_rector_assignment(self):
        from tasks.permissions import can_unassign_user
        from tasks.services import unassign_user
        self.assertFalse(can_unassign_user(self.dept_head, self.task, self.a_emp1))
        with self.assertRaises(ValidationError):
            unassign_user(self.dept_head, self.task, self.a_emp1)

    def test_dept_head_can_unassign_their_own_assignment(self):
        from tasks.permissions import can_unassign_user
        from tasks.services import unassign_user
        self.assertTrue(can_unassign_user(self.dept_head, self.task, self.a_emp2))
        unassign_user(self.dept_head, self.task, self.a_emp2)
        self.assertFalse(self.task.assignments.filter(user=self.emp2).exists())

    def test_rector_can_unassign_anyone(self):
        from tasks.permissions import can_unassign_user
        from tasks.services import unassign_user
        self.assertTrue(can_unassign_user(self.rector, self.task, self.a_emp1))
        self.assertTrue(can_unassign_user(self.rector, self.task, self.a_emp2))

    def test_submitted_task_locks_manage_assigned_for_vice_rector_dept_head_employee(self):
        """
        When an employee submits the task (it is in 'Submitted Tasks' awaiting approval),
        the relevant Vice Rector, Department Head, and Employee cannot manage assigned:
        - can_assign_task returns False
        - can_assign_employees_to_task returns False
        - can_unassign_user returns False
        - assign_task and unassign_user raise ValidationError
        """
        from tasks.models import TaskAssignment
        from tasks.permissions import (
            can_assign_employees_to_task,
            can_assign_task,
            can_unassign_user,
        )
        from tasks.services import assign_task, unassign_user

        # Employee submits work
        self.a_emp1.assignment_status = TaskAssignment.AssignmentStatus.SUBMITTED
        self.a_emp1.progress = 100
        self.a_emp1.save()

        # Vice Rector cannot manage assigned
        self.assertFalse(can_assign_task(self.vr, self.task))
        self.assertFalse(can_assign_employees_to_task(self.vr, self.task))
        self.assertFalse(can_unassign_user(self.vr, self.task, self.a_emp2))

        # Department Head cannot manage assigned
        self.assertFalse(can_assign_task(self.dept_head, self.task))
        self.assertFalse(can_assign_employees_to_task(self.dept_head, self.task))
        self.assertFalse(can_unassign_user(self.dept_head, self.task, self.a_emp2))

        # Employee cannot manage assigned
        self.assertFalse(can_assign_task(self.emp1, self.task))
        self.assertFalse(can_assign_employees_to_task(self.emp1, self.task))
        self.assertFalse(can_unassign_user(self.emp1, self.task, self.a_emp2))

        # Service layer blocks assignment modification by Dept Head or Vice Rector
        with self.assertRaises(ValidationError):
            assign_task(self.dept_head, self.task, [self.emp3])

        with self.assertRaises(ValidationError):
            assign_task(self.vr, self.task, [self.emp3])

        with self.assertRaises(ValidationError):
            unassign_user(self.dept_head, self.task, self.a_emp2)

        with self.assertRaises(ValidationError):
            unassign_user(self.vr, self.task, self.a_emp2)

        # Rector retains administrative authority if needed
        self.assertTrue(can_assign_task(self.rector, self.task))
        self.assertTrue(can_unassign_user(self.rector, self.task, self.a_emp2))


class TaskHierarchyAndDelegationTests(TestCase):
    def setUp(self):
        self.dept_it = Department.objects.create(name='IT Department', code='IT_DEPT')
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN_DEPT')
        self.dept_hr = Department.objects.create(name='HR Department', code='HR_DEPT')

        self.role_rector, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.role_vr, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.role_head, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.role_emp, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.rector = User.objects.create_user(
            username='official_rector',
            email='rector@univ.uz',
            password='Password123!',
        )
        self.rector.roles.add(self.role_rector)

        self.vr_academic = User.objects.create_user(
            username='vr_academic',
            email='vr_acad@univ.uz',
            password='Password123!',
        )
        self.vr_academic.roles.add(self.role_vr)
        assign_vice_rector_responsibility(self.vr_academic, self.dept_it, actor=self.rector)

        self.head_it = User.objects.create_user(
            username='head_it',
            email='head_it@univ.uz',
            password='Password123!',
            department=self.dept_it,
        )
        self.head_it.roles.add(self.role_head)
        assign_department_head(self.dept_it, self.head_it, actor=self.rector)

        self.head_fin = User.objects.create_user(
            username='head_fin',
            email='head_fin@univ.uz',
            password='Password123!',
            department=self.dept_fin,
        )
        self.head_fin.roles.add(self.role_head)
        assign_department_head(self.dept_fin, self.head_fin, actor=self.rector)

        self.emp_it = User.objects.create_user(
            username='emp_it',
            email='emp_it@univ.uz',
            password='Password123!',
            department=self.dept_it,
        )
        self.emp_it.roles.add(self.role_emp)

        self.emp_fin = User.objects.create_user(
            username='emp_fin',
            email='emp_fin@univ.uz',
            password='Password123!',
            department=self.dept_fin,
        )
        self.emp_fin.roles.add(self.role_emp)

        self.superadmin = User.objects.create_user(
            username='sysadmin',
            email='admin@univ.uz',
            password='Password123!',
            is_superuser=True,
        )

    def test_rector_cross_department_task_creation(self):
        task = create_task(
            actor=self.rector,
            title='University Digital Transformation Initiative',
            description='Cross-department initiative',
            responsible_department=self.dept_it,
            initial_assignees=[self.emp_it, self.emp_fin],
            primary_assignee=self.emp_it,
            status=Task.Status.CREATED,
        )
        task.refresh_from_db()
        self.assertEqual(task.responsible_department, self.dept_it)
        self.assertIn(self.dept_fin, task.secondary_departments.all())
        self.assertEqual(task.assignments.count(), 2)
        self.assertEqual(task.primary_assignee, self.emp_it)

    def test_department_head_scope_restrictions(self):
        # 1. Dept Head creates task for own department with own employee -> succeeds
        task = create_task(
            actor=self.head_it,
            title='Internal IT Audit',
            description='Audit IT systems',
            responsible_department=self.dept_it,
            initial_assignees=[self.emp_it],
            primary_assignee=self.emp_it,
            status=Task.Status.CREATED,
        )
        self.assertEqual(task.responsible_department, self.dept_it)
        self.assertEqual(task.creator, self.head_it)

        # 2. Dept Head cannot create task for another department
        with self.assertRaises(ValidationError):
            create_task(
                actor=self.head_it,
                title='Unauthorized Finance Task',
                description='Should fail',
                responsible_department=self.dept_fin,
            )

        # 3. Dept Head cannot assign employee from another department
        with self.assertRaises(ValidationError):
            create_task(
                actor=self.head_it,
                title='Unauthorized Cross Assign',
                description='Should fail',
                responsible_department=self.dept_it,
                initial_assignees=[self.emp_fin],
            )

        # 4. Dept Head cannot assign task to Rector or Vice Rector
        with self.assertRaises(ValidationError):
            assign_task(self.head_it, task, [self.rector])

        with self.assertRaises(ValidationError):
            assign_task(self.head_it, task, [self.vr_academic])

        with self.assertRaises(ValidationError):
            assign_task(self.head_it, task, [self.superadmin])

    def test_vice_rector_scope_restrictions(self):
        # 1. Vice Rector can create task for supervised department
        task = create_task(
            actor=self.vr_academic,
            title='Supervised Dept Task',
            description='IT plan',
            responsible_department=self.dept_it,
            initial_assignees=[self.emp_it],
            primary_assignee=self.emp_it,
            status=Task.Status.CREATED,
        )
        self.assertEqual(task.responsible_department, self.dept_it)

        # 2. Vice Rector cannot create task for unsupervised department
        with self.assertRaises(ValidationError):
            create_task(
                actor=self.vr_academic,
                title='Unsupervised Dept Task',
                description='Finance plan',
                responsible_department=self.dept_fin,
            )

        # 3. Vice Rector cannot assign task to Rector or Superadmin
        with self.assertRaises(ValidationError):
            assign_task(self.vr_academic, task, [self.rector])

        with self.assertRaises(ValidationError):
            assign_task(self.vr_academic, task, [self.superadmin])

    def test_acting_rector_delegation_powers(self):
        # Delegate acting rector authority to vr_academic
        delegation = assign_acting_rector(
            rector=self.rector,
            acting_rector=self.vr_academic,
            actor=self.rector,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=14),
            reason='Rector international academic mission',
        )
        self.assertTrue(self.vr_academic.can_act_as_rector)
        self.assertTrue(self.vr_academic.is_acting_rector)

        # Acting Rector can create cross-department task university-wide
        task = create_task(
            actor=self.vr_academic,
            title='Acting Rector Multi-Department Directive',
            description='Directive during rector absence',
            responsible_department=self.dept_fin,
            initial_assignees=[self.emp_fin, self.emp_it],
            primary_assignee=self.emp_fin,
            status=Task.Status.CREATED,
        )
        self.assertEqual(task.responsible_department, self.dept_fin)
        self.assertIn(self.dept_it, task.secondary_departments.all())

        # Progress the task through workflow to completion
        assignment = task.assignments.get(user=self.emp_fin)
        accept_assignment(self.emp_fin, assignment)
        assignment.refresh_from_db()
        submission = submit_assignment(
            actor=self.emp_fin,
            assignment=assignment,
            submission_text='Finance report completed',
        )
        assignment.refresh_from_db()
        first_approve_assignment(self.head_fin, assignment, notes='Department level verified')

        # Acting Rector can perform second/final approval
        assignment.refresh_from_db()
        final_approve_assignment(self.vr_academic, assignment, notes='Acting Rector approved')
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.COMPLETED)

        # Acting Rector can digitally sign the task with RECTOR_SIGNATURE
        sig = sign_task(task, self.vr_academic)
        self.assertEqual(sig.signature_type, ElectronicSignature.SignatureType.RECTOR_SIGNATURE)
        self.assertEqual(sig.signer, self.vr_academic)

        # Once delegation is revoked, vr_academic loses rector powers
        revoke_acting_rector(delegation, actor=self.rector)
        self.vr_academic.refresh_from_db()
        self.assertFalse(self.vr_academic.can_act_as_rector)
        self.assertFalse(self.vr_academic.is_acting_rector)


class MultiDepartmentAndDynamicAssignmentViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.role_rector, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.role_vr, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.role_head, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.role_emp, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.dept_it = Department.objects.create(name='IT Department', code='IT_DEPT')
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN_DEPT')
        self.tt = TaskType.objects.create(name='General Directive', code='GENERAL_DIRECTIVE')

        self.rector = User.objects.create_user(
            username='rector_user',
            email='rector@univ.uz',
            password='Password123!',
        )
        self.rector.roles.add(self.role_rector)

        self.vr = User.objects.create_user(
            username='vr_user',
            email='vr@univ.uz',
            password='Password123!',
        )
        self.vr.roles.add(self.role_vr)
        assign_vice_rector_responsibility(self.vr, self.dept_it, actor=self.rector)

        self.head_it = User.objects.create_user(
            username='head_it_user',
            email='head_it@univ.uz',
            password='Password123!',
            department=self.dept_it,
        )
        self.head_it.roles.add(self.role_head)
        assign_department_head(self.dept_it, self.head_it, actor=self.rector)

        self.emp_it = User.objects.create_user(
            username='emp_it_user',
            first_name='Ali',
            last_name='Valiyev',
            email='emp_it@univ.uz',
            password='Password123!',
            department=self.dept_it,
        )
        self.emp_it.roles.add(self.role_emp)

        self.emp_fin = User.objects.create_user(
            username='emp_fin_user',
            first_name='Salim',
            last_name='Karimov',
            email='emp_fin@univ.uz',
            password='Password123!',
            department=self.dept_fin,
        )
        self.emp_fin.roles.add(self.role_emp)

    def test_task_create_form_scoping_per_role(self):
        from tasks.forms import TaskCreateForm

        # Rector sees all departments in primary and secondary
        form_rector = TaskCreateForm(user=self.rector)
        self.assertIn(self.dept_it, form_rector.fields['responsible_department'].queryset)
        self.assertIn(self.dept_fin, form_rector.fields['secondary_departments'].queryset)

        # Vice Rector sees only supervised departments
        form_vr = TaskCreateForm(user=self.vr)
        self.assertIn(self.dept_it, form_vr.fields['secondary_departments'].queryset)
        self.assertNotIn(self.dept_fin, form_vr.fields['secondary_departments'].queryset)

        # Department Head has secondary_departments hidden
        form_head = TaskCreateForm(user=self.head_it)
        self.assertTrue(form_head.fields['secondary_departments'].widget.is_hidden)

    def test_task_create_view_get_context_and_json(self):
        self.client.login(username='rector_user', password='Password123!')
        res = self.client.get(reverse('task_create'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('employees_json', res.context)

        import json
        emps = json.loads(res.context['employees_json'])
        emp_ids = [e['id'] for e in emps]
        self.assertIn(str(self.emp_it.id), emp_ids)
        self.assertIn(str(self.emp_fin.id), emp_ids)

        # Check template rendered components
        self.assertContains(res, 'secondaryDepartmentsWrapper')
        self.assertContains(res, 'employeeAssignmentCard')
        self.assertContains(res, 'employeeCardsContainer')

    def test_task_create_view_post_with_multiple_departments_and_assignees(self):
        self.client.login(username='rector_user', password='Password123!')
        res = self.client.post(
            reverse('task_create'),
            {
                'title': 'Cross-Department Comprehensive Review',
                'description': 'IT and Finance review',
                'responsible_department': self.dept_it.id,
                'secondary_departments': [self.dept_fin.id],
                'task_type': self.tt.id,
                'priority': Task.Priority.HIGH,
                'complexity': Task.Complexity.COMPLEX,
                'initial_assignees': [self.emp_it.id, self.emp_fin.id],
                'primary_assignee': self.emp_it.id,
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        task = Task.objects.filter(title='Cross-Department Comprehensive Review').first()
        self.assertIsNotNone(task)
        self.assertEqual(task.responsible_department, self.dept_it)
        self.assertIn(self.dept_fin, task.secondary_departments.all())
        self.assertEqual(task.assignments.count(), 2)
        self.assertEqual(task.primary_assignee, self.emp_it)


class TaskDetailSmartRoutingTests(TestCase):
    def setUp(self):
        translation.activate('en')
        self.client = Client()
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'
        self.role_rector, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.role_vr, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.role_head, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.role_emp, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.dept_it = Department.objects.create(name='Information Technology', code='IT_DEPT')
        self.tt = TaskType.objects.create(name='Document Preparation', code='DOC_PREP')

        # Rector Akbar Rahmatov
        self.rector = User.objects.create_user(
            username='rector_akbar',
            first_name='Akbar',
            last_name='Rahmatov',
            email='akbar@univ.uz',
            password='Password123!',
        )
        self.rector.roles.add(self.role_rector)

        # Vice Rector Dilshod Alimov
        self.vr = User.objects.create_user(
            username='vr_dilshod',
            first_name='Dilshod',
            last_name='Alimov',
            email='dilshod@univ.uz',
            password='Password123!',
        )
        self.vr.roles.add(self.role_vr)
        assign_vice_rector_responsibility(self.vr, self.dept_it, actor=self.rector)

        # Department Head Bekzod Nazarov
        self.head_it = User.objects.create_user(
            username='head_bekzod',
            first_name='Bekzod',
            last_name='Nazarov',
            email='bekzod@univ.uz',
            password='Password123!',
            department=self.dept_it,
        )
        self.head_it.roles.add(self.role_head)
        assign_department_head(self.dept_it, self.head_it, actor=self.rector)

        # Employee Aziz Sobirov
        self.emp_aziz = User.objects.create_user(
            username='emp_aziz',
            first_name='Aziz',
            last_name='Sobirov',
            email='aziz@univ.uz',
            password='Password123!',
            department=self.dept_it,
        )
        self.emp_aziz.roles.add(self.role_emp)

        # Employee Madina Ibragimova
        self.emp_madina = User.objects.create_user(
            username='emp_madina',
            first_name='Madina',
            last_name='Ibragimova',
            email='madina@univ.uz',
            password='Password123!',
            department=self.dept_it,
        )
        self.emp_madina.roles.add(self.role_emp)

        # Rector creates task for IT department
        from tasks.services import create_task
        self.task = create_task(
            actor=self.rector,
            title='Test Task',
            description='Test description',
            responsible_department=self.dept_it,
            task_type=self.tt,
        )

    def tearDown(self):
        translation.deactivate()
        super().tearDown()

    def test_rector_creator_sees_management_view_image_2(self):
        self.client.login(username='rector_akbar', password='Password123!')
        res = self.client.get(reverse('task_detail', kwargs={'pk': self.task.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'tasks/task_detail.html')
        self.assertContains(res, 'Manage Assignees')

    def test_vice_rector_assigns_and_sees_management_view_image_2(self):
        from tasks.services import assign_task
        assign_task(
            actor=self.vr,
            task=self.task,
            users=[self.head_it, self.emp_aziz, self.emp_madina],
            primary_user=self.head_it,
        )

        # Vice Rector opens task -> Image 2 (task_detail.html)
        self.client.login(username='vr_dilshod', password='Password123!')
        res = self.client.get(reverse('task_detail', kwargs={'pk': self.task.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'tasks/task_detail.html')
        self.assertContains(res, 'Manage Assignees')

    def test_assigned_employee_redirected_to_image_1(self):
        from tasks.services import assign_task
        assignments = assign_task(
            actor=self.vr,
            task=self.task,
            users=[self.head_it, self.emp_aziz],
            primary_user=self.head_it,
        )
        aziz_assignment = [a for a in assignments if a.user_id == self.emp_aziz.id][0]

        # Aziz opens task -> redirects to Image 1 (assignment_detail.html)
        self.client.login(username='emp_aziz', password='Password123!')
        res = self.client.get(reverse('task_detail', kwargs={'pk': self.task.pk}))
        expected_url = reverse('assignment_detail', kwargs={'pk': aziz_assignment.pk})
        self.assertRedirects(res, expected_url)

        # Visiting the redirected URL yields assignment_detail.html (Image 1)
        res_detail = self.client.get(expected_url)
        self.assertEqual(res_detail.status_code, 200)
        self.assertTemplateUsed(res_detail, 'workflow/assignment_detail.html')
        self.assertContains(res_detail, 'Accept Task')

    def test_primary_assignee_head_it_assigned_by_vr_redirected_to_image_1(self):
        from tasks.services import assign_task
        assignments = assign_task(
            actor=self.vr,
            task=self.task,
            users=[self.head_it, self.emp_aziz],
            primary_user=self.head_it,
        )
        head_assignment = [a for a in assignments if a.user_id == self.head_it.id][0]

        # Bekzod Nazarov (assigned as primary by Dilshod Alimov) opens task -> Image 1 (assignment_detail)
        self.client.login(username='head_bekzod', password='Password123!')
        res = self.client.get(reverse('task_detail', kwargs={'pk': self.task.pk}))
        expected_url = reverse('assignment_detail', kwargs={'pk': head_assignment.pk})
        self.assertRedirects(res, expected_url)

        # Bekzod Nazarov has Management View toggle available on Image 1
        res_detail = self.client.get(expected_url)
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'Management View')

    def test_head_it_assigner_sees_management_view_image_2(self):
        # Suppose Head IT is the one who assigns employees (not assigned themselves)
        from tasks.services import assign_task
        assign_task(
            actor=self.head_it,
            task=self.task,
            users=[self.emp_aziz, self.emp_madina],
            primary_user=self.emp_aziz,
        )

        # Head IT did Manage Task Assignees -> sees Image 2
        self.client.login(username='head_bekzod', password='Password123!')
        res = self.client.get(reverse('task_detail', kwargs={'pk': self.task.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'tasks/task_detail.html')

    def test_view_manage_override_parameter(self):
        from tasks.services import assign_task
        assign_task(
            actor=self.vr,
            task=self.task,
            users=[self.head_it, self.emp_aziz],
            primary_user=self.head_it,
        )

        # Head IT with ?view=manage opens Image 2 directly
        self.client.login(username='head_bekzod', password='Password123!')
        res = self.client.get(reverse('task_detail', kwargs={'pk': self.task.pk}) + '?view=manage')
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'tasks/task_detail.html')
        self.assertContains(res, 'My Work Area')

    def test_manage_task_assignees_ui_and_save(self):
        self.client.login(username='rector_akbar', password='Password123!')
        url = reverse('task_assign', kwargs={'pk': self.task.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'tasks/task_assign.html')
        self.assertIn('employees_json', res.context)
        self.assertContains(res, 'Manage Task Assignees')
        self.assertContains(res, 'Aziz Sobirov')
        self.assertContains(res, 'Madina Ibragimova')
        self.assertContains(res, 'employeeCardsContainer')

        # Submit assigning both Aziz and Madina with Madina as primary
        post_data = {
            'assignees': [str(self.emp_aziz.id), str(self.emp_madina.id)],
            'primary_assignee': str(self.emp_madina.id),
        }
        res_post = self.client.post(url, post_data)
        self.assertRedirects(res_post, reverse('task_detail', kwargs={'pk': self.task.pk}))

        # Verify assignments updated
        self.assertEqual(self.task.assignments.count(), 2)
        primary = self.task.assignments.filter(is_primary=True).first()
        self.assertIsNotNone(primary)
        self.assertEqual(primary.user_id, self.emp_madina.id)

    def test_task_list_all_vs_under_control(self):
        # Create a second task that is completed
        from tasks.services import create_task
        completed_task = create_task(
            actor=self.rector,
            title='Completed Task',
            description='Finished work',
            responsible_department=self.dept_it,
            task_type=self.tt,
        )
        completed_task.status = Task.Status.COMPLETED
        completed_task.save()

        # Login as Head of IT
        self.client.login(username='head_bekzod', password='Password123!')

        # 1. All Tasks view (/tasks/) includes both active and completed tasks
        res_all = self.client.get(reverse('task_list'))
        self.assertEqual(res_all.status_code, 200)
        tasks_all = list(res_all.context['tasks'])
        self.assertIn(self.task, tasks_all)
        self.assertIn(completed_task, tasks_all)

        # 2. Under Control view (/tasks/?scope=control) only includes active tasks under supervision
        res_ctrl = self.client.get(reverse('task_list') + '?scope=control')
        self.assertEqual(res_ctrl.status_code, 200)
        tasks_ctrl = list(res_ctrl.context['tasks'])
        self.assertIn(self.task, tasks_ctrl)
        self.assertNotIn(completed_task, tasks_ctrl)

        # Context statuses in control scope exclude completed/cancelled/archived
        status_keys = [c[0] for c in res_ctrl.context['statuses']]
        self.assertNotIn(Task.Status.COMPLETED, status_keys)
        self.assertNotIn(Task.Status.CANCELLED, status_keys)
        self.assertNotIn(Task.Status.ARCHIVED, status_keys)



