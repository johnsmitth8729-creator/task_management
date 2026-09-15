import datetime
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from ai_assistant.context_builder import RoleContextBuilder
from ai_assistant.engine import (
    AIAssistantEngine,
    ExecutiveReportGenerator,
    RiskDetectionEngine,
)
from ai_assistant.models import (
    AIConversation,
    AIMessage,
    ExecutiveBriefing,
    ManagementRiskIndicator,
)
from organization.models import Department, Position, DepartmentResponsibility
from tasks.models import Task, TaskAssignment, TaskSubmission, TaskType

User = get_user_model()


class AIAssistantEngineTests(TestCase):
    def setUp(self):
        self.dept_math = Department.objects.create(name='Mathematics', code='MATH_DEPT')
        self.dept_cs = Department.objects.create(name='Computer Science', code='CS_DEPT')

        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Dept Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.rector = User.objects.create_user(
            username='rector_ai',
            email='rector_ai@uni.edu',
            password='Password123!',
        )
        self.rector.roles.add(self.rector_role)

        self.vice_rector = User.objects.create_user(
            username='vr_ai',
            email='vr_ai@uni.edu',
            password='Password123!',
        )
        self.vice_rector.roles.add(self.vr_role)
        DepartmentResponsibility.objects.create(
            vice_rector=self.vice_rector,
            department=self.dept_cs,
            is_active=True
        )

        self.head = User.objects.create_user(
            username='head_ai',
            email='head_ai@uni.edu',
            password='Password123!',
            department=self.dept_cs,
        )
        self.head.roles.add(self.head_role)
        self.dept_cs.head = self.head
        self.dept_cs.save()

        self.employee = User.objects.create_user(
            username='emp_ai',
            email='emp_ai@uni.edu',
            password='Password123!',
            department=self.dept_cs,
        )
        self.employee.roles.add(self.emp_role)

        self.task_type = TaskType.objects.create(name='Academic AI', code='AI_TASK')
        self.task = Task.objects.create(
            title='AI Curriculum Development',
            priority=Task.Priority.URGENT,
            task_type=self.task_type,
            creator=self.rector,
            responsible_department=self.dept_cs,
            deadline=timezone.now().date() + datetime.timedelta(days=2),
        )
        TaskAssignment.objects.create(
            task=self.task,
            user=self.employee,
            assigned_by=self.rector,
        )

    def test_role_context_builder_scoping(self):
        # 1. Rector Context -> University Wide
        rector_ctx = RoleContextBuilder.build_context(self.rector)
        self.assertEqual(rector_ctx['scope'], 'UNIVERSITY_WIDE')
        self.assertIn('total_tasks', rector_ctx['metrics'])

        # 2. Vice Rector Context -> Scoped to CS Dept
        vr_ctx = RoleContextBuilder.build_context(self.vice_rector)
        self.assertEqual(vr_ctx['scope'], 'VICE_RECTOR_SECTOR')
        self.assertIn('Computer Science', vr_ctx['accessible_departments'])
        self.assertNotIn('Mathematics', vr_ctx['accessible_departments'])

        # 3. Department Head Context -> Scoped to CS Dept
        head_ctx = RoleContextBuilder.build_context(self.head)
        self.assertEqual(head_ctx['scope'], 'DEPARTMENT')
        self.assertIn('dept_total_tasks', head_ctx['metrics'])

        # 4. Employee Context -> Personal assignments only
        emp_ctx = RoleContextBuilder.build_context(self.employee)
        self.assertEqual(emp_ctx['scope'], 'PERSONAL')
        self.assertIn('my_total_assignments', emp_ctx['metrics'])

    def test_risk_detection_engine(self):
        # Create overdue tasks in Math dept
        for i in range(4):
            Task.objects.create(
                title=f'Overdue Math Task {i}',
                priority=Task.Priority.HIGH,
                task_type=self.task_type,
                creator=self.rector,
                responsible_department=self.dept_math,
                deadline=timezone.now().date() - datetime.timedelta(days=3),
                status=Task.Status.IN_PROGRESS,
            )

        risks = RiskDetectionEngine.run_full_risk_assessment()
        self.assertGreaterEqual(len(risks), 1)
        spike_risk = ManagementRiskIndicator.objects.filter(
            risk_type=ManagementRiskIndicator.RiskType.DEADLINE_SPIKE,
            department=self.dept_math
        ).first()
        self.assertIsNotNone(spike_risk)

    def test_executive_report_generator(self):
        briefing = ExecutiveReportGenerator.generate_weekly_briefing(self.rector)
        self.assertIsNotNone(briefing)
        self.assertIn('Executive Intelligence Briefing', briefing.title)
        self.assertIn('## 1. Executive Summary', briefing.summary_markdown)
        self.assertIn('## 2. Key Performance Indicators', briefing.summary_markdown)

    def test_ai_assistant_ask_and_grounding(self):
        msg, conv = AIAssistantEngine.ask(
            user=self.rector,
            prompt='Give me a summary of overdue tasks and risks in the university.'
        )
        self.assertEqual(msg.role, AIMessage.Role.ASSISTANT)
        self.assertEqual(conv.user, self.rector)
        self.assertIn('Risk & Delay Assessment', msg.content)
        self.assertTrue(conv.messages.filter(role=AIMessage.Role.USER).exists())


class AIAssistantViewsTests(TestCase):
    def setUp(self):
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.rector = User.objects.create_user(
            username='rector_v',
            email='rector_v@uni.edu',
            password='Password123!',
        )
        self.rector.roles.add(self.rector_role)

        self.employee = User.objects.create_user(
            username='emp_v',
            email='emp_v@uni.edu',
            password='Password123!',
        )
        self.employee.roles.add(self.emp_role)

    def test_chat_view_and_post(self):
        self.client.force_login(self.employee)
        res = self.client.get(reverse('ai_assistant:chat'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'AI Management Assistant')

        # Post a prompt
        res_post = self.client.post(reverse('ai_assistant:chat'), {
            'prompt': 'What is my current task status?'
        })
        self.assertEqual(res_post.status_code, 302)
        self.assertTrue(AIConversation.objects.filter(user=self.employee).exists())

    def test_risk_center_view_and_resolve(self):
        risk = ManagementRiskIndicator.objects.create(
            risk_type=ManagementRiskIndicator.RiskType.APPROVAL_BOTTLENECK,
            severity=ManagementRiskIndicator.Severity.HIGH,
            title='Test Approval Delay',
            description='Test bottleneck description.',
        )
        self.client.force_login(self.rector)
        res = self.client.get(reverse('ai_assistant:risk_center'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Test Approval Delay')

        # Resolve risk
        res_resolve = self.client.post(reverse('ai_assistant:risk_resolve', kwargs={'pk': risk.id}))
        self.assertEqual(res_resolve.status_code, 302)
        risk.refresh_from_db()
        self.assertTrue(risk.is_resolved)

    def test_briefing_views(self):
        briefing = ExecutiveReportGenerator.generate_weekly_briefing(self.rector)
        self.client.force_login(self.rector)
        res_list = self.client.get(reverse('ai_assistant:briefing_list'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, briefing.title)

        res_detail = self.client.get(reverse('ai_assistant:briefing_detail', kwargs={'pk': briefing.id}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'University Management Intelligence Report')
