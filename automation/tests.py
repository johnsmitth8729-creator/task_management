import datetime
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from automation.engine import (
    evaluate_rules_for_event,
    generate_due_recurring_tasks,
    match_conditions,
    process_escalation_policies,
    process_sla_checks,
)
from automation.models import (
    AutomationExecution,
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)
from automation.selectors import (
    get_sla_status_for_task,
)
from core.models import Notification
from organization.models import Department, Position
from tasks.models import Task, TaskAssignment, TaskType

User = get_user_model()


class AutomationEngineTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='IT Department', code='IT_DEPT')
        self.pos = Position.objects.create(name='Developer', code='DEV_POS', department=self.dept)
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.employee_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.superadmin = User.objects.create_superuser(
            username='admin_test',
            email='admin@uni.edu',
            password='Password123!',
            first_name='Super',
            last_name='Admin',
        )
        self.rector = User.objects.create_user(
            username='rector_test',
            email='rector@uni.edu',
            password='Password123!',
            first_name='University',
            last_name='Rector',
        )
        self.rector.roles.add(self.rector_role)

        self.employee = User.objects.create_user(
            username='employee_test',
            email='emp@uni.edu',
            password='Password123!',
            first_name='John',
            last_name='Doe',
            department=self.dept,
            position=self.pos,
        )
        self.employee.roles.add(self.employee_role)

        self.task_type = TaskType.objects.create(name='Technical', code='TECH')
        self.task = Task.objects.create(
            title='Test Server Outage',
            description='Production down',
            priority=Task.Priority.URGENT,
            task_type=self.task_type,
            creator=self.superadmin,
            responsible_department=self.dept,
            deadline=timezone.now().date() + datetime.timedelta(days=1),
        )

    def test_condition_matching(self):
        conditions = {
            'priority': 'URGENT',
            'department_code': 'IT_DEPT',
        }
        self.assertTrue(match_conditions(conditions, self.task))

        mismatch_conditions = {
            'priority': 'LOW',
        }
        self.assertFalse(match_conditions(mismatch_conditions, self.task))

    def test_automation_rule_execution(self):
        rule = AutomationRule.objects.create(
            name='Auto Assign High Priority IT Tasks',
            trigger_event=AutomationRule.TriggerEvent.TASK_CREATED,
            action_type=AutomationRule.ActionType.AUTO_ASSIGN,
            action_config={'user_id': str(self.employee.id)},
            conditions={'priority': 'URGENT'},
            created_by=self.superadmin,
            is_active=True,
        )
        executions = evaluate_rules_for_event(
            trigger_event=AutomationRule.TriggerEvent.TASK_CREATED,
            target_obj=self.task,
            user=self.superadmin,
        )
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].status, AutomationExecution.Status.SUCCESS)
        self.assertTrue(TaskAssignment.objects.filter(task=self.task, user=self.employee).exists())

    def test_sla_policy_and_monitoring(self):
        sla = SLAPolicy.objects.create(
            name='Critical SLA Policy',
            priority=SLAPolicy.Priority.CRITICAL,
            first_response_hours=2,
            resolution_hours=24,
            warning_threshold_percent=80,
            is_active=True,
        )
        self.task.priority = 'CRITICAL'
        self.task.save()
        status_info = get_sla_status_for_task(self.task)
        self.assertIsNotNone(status_info)
        self.assertEqual(status_info['policy'].id, sla.id)
        self.assertIn(status_info['status'], ['ON_TRACK', 'WARNING', 'BREACHED'])

        # Process SLA checks
        breaches = process_sla_checks()
        self.assertIsInstance(breaches, int)

    def test_escalation_policy_evaluation(self):
        # Create an overdue task
        overdue_task = Task.objects.create(
            title='Overdue Task',
            priority=Task.Priority.HIGH,
            creator=self.superadmin,
            responsible_department=self.dept,
            deadline=timezone.now().date() - datetime.timedelta(days=2),
            status=Task.Status.IN_PROGRESS,
        )
        esc_policy = EscalationPolicy.objects.create(
            name='Stage 1 Overdue Escalation',
            trigger_type=EscalationPolicy.TriggerType.DEADLINE_PASSED,
            hours_threshold=24,
            escalate_to_role=EscalationPolicy.EscalateToRole.RECTOR,
            is_active=True,
        )
        escalations = process_escalation_policies()
        self.assertGreaterEqual(escalations, 1)
        # Verify in-app notification sent to rector
        self.assertTrue(
            Notification.objects.filter(recipient=self.rector, task=overdue_task).exists()
        )

    def test_recurring_task_rule_idempotency(self):
        recur_rule = RecurringTaskRule.objects.create(
            title='Weekly System Backup Check',
            description='Perform weekly server snapshot verification.',
            priority=Task.Priority.HIGH,
            recurrence_type=RecurringTaskRule.RecurrenceType.WEEKLY,
            responsible_department=self.dept,
            created_by=self.superadmin,
            deadline_offset_days=3,
            is_active=True,
        )
        recur_rule.assignees.add(self.employee)

        created_tasks = generate_due_recurring_tasks()
        self.assertEqual(len(created_tasks), 1)
        created_task = created_tasks[0]
        self.assertIn('Weekly System Backup Check', created_task.title)
        self.assertEqual(created_task.responsible_department, self.dept)

        # Running again within the same cycle should be idempotent (0 tasks created)
        second_run = generate_due_recurring_tasks()
        self.assertEqual(len(second_run), 0)


class AutomationViewRBAC_Tests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='HR Department', code='HR_DEPT')
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.employee_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.superadmin = User.objects.create_superuser(
            username='admin_rbac',
            email='admin_rbac@uni.edu',
            password='Password123!',
        )
        self.rector = User.objects.create_user(
            username='rector_rbac',
            email='rector_rbac@uni.edu',
            password='Password123!',
        )
        self.rector.roles.add(self.rector_role)

        self.employee = User.objects.create_user(
            username='employee_rbac',
            email='emp_rbac@uni.edu',
            password='Password123!',
            department=self.dept,
        )
        self.employee.roles.add(self.employee_role)

    def test_dashboard_access(self):
        # Superadmin allowed
        self.client.force_login(self.superadmin)
        res = self.client.get(reverse('automation:dashboard'))
        self.assertEqual(res.status_code, 200)

        # Rector allowed
        self.client.force_login(self.rector)
        res = self.client.get(reverse('automation:dashboard'))
        self.assertEqual(res.status_code, 200)

        # Standard employee forbidden / 403
        self.client.force_login(self.employee)
        res = self.client.get(reverse('automation:dashboard'))
        self.assertEqual(res.status_code, 403)

    def test_rule_list_access(self):
        self.client.force_login(self.superadmin)
        res = self.client.get(reverse('automation:rule_list'))
        self.assertEqual(res.status_code, 200)

        self.client.force_login(self.employee)
        res = self.client.get(reverse('automation:rule_list'))
        self.assertEqual(res.status_code, 403)
