from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from analytics.models import AnalyticsThresholdConfig, SavedReportConfiguration
from analytics.selectors import (
    get_bottleneck_metrics,
    get_deadline_metrics,
    get_department_comparison_data,
    get_employee_personal_metrics,
    get_executive_metrics,
    parse_date_range,
)
from organization.models import Department, DepartmentResponsibility, Position
from tasks.models import Task, TaskApproval, TaskAssignment, TaskSubmission

User = get_user_model()


class AnalyticsTests(TestCase):
    def setUp(self):
        # Create roles
        self.role_rector, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.role_vice_rector, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.role_dept_head, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.role_employee, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})
        self.role_hr, _ = Role.objects.get_or_create(code=Role.Codes.HR, defaults={'name': 'HR Manager'})
        self.role_finance, _ = Role.objects.get_or_create(code=Role.Codes.FINANCE, defaults={'name': 'Finance Officer'})

        # Create departments
        self.dept_it = Department.objects.create(name='IT Department', code='IT', is_active=True)
        self.dept_lib = Department.objects.create(name='Library Department', code='LIB', is_active=True)
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN', is_active=True)

        # Positions
        self.pos_it = Position.objects.create(name='Software Engineer', code='SE_IT', department=self.dept_it)
        self.pos_lib = Position.objects.create(name='Librarian', code='LIB_STF', department=self.dept_lib)

        # Users
        self.superadmin = User.objects.create_superuser(
            username='admin_user', email='admin_user@uni.edu', password='Password123!'
        )

        self.rector = User.objects.create_user(
            username='rector_user', email='rector_user@uni.edu', password='Password123!', first_name='Rector', last_name='Global'
        )
        self.rector.roles.add(self.role_rector)

        self.vice_rector = User.objects.create_user(
            username='vr_user', email='vr_user@uni.edu', password='Password123!', first_name='Vice', last_name='Rector'
        )
        self.vice_rector.roles.add(self.role_vice_rector)
        # Supervise IT and Library
        DepartmentResponsibility.objects.create(vice_rector=self.vice_rector, department=self.dept_it, is_active=True)
        DepartmentResponsibility.objects.create(vice_rector=self.vice_rector, department=self.dept_lib, is_active=True)

        self.head_it = User.objects.create_user(
            username='head_it', email='head_it@uni.edu', password='Password123!', department=self.dept_it
        )
        self.head_it.roles.add(self.role_dept_head)

        self.head_lib = User.objects.create_user(
            username='head_lib', email='head_lib@uni.edu', password='Password123!', department=self.dept_lib
        )
        self.head_lib.roles.add(self.role_dept_head)

        self.emp_it = User.objects.create_user(
            username='emp_it', email='emp_it@uni.edu', password='Password123!', department=self.dept_it, position=self.pos_it
        )
        self.emp_it.roles.add(self.role_employee)

        self.emp_lib = User.objects.create_user(
            username='emp_lib', email='emp_lib@uni.edu', password='Password123!', department=self.dept_lib, position=self.pos_lib
        )
        self.emp_lib.roles.add(self.role_employee)

        self.user_hr = User.objects.create_user(username='hr_mgr', email='hr_mgr@uni.edu', password='Password123!')
        self.user_hr.roles.add(self.role_hr)

        self.user_finance = User.objects.create_user(username='fin_officer', email='fin_officer@uni.edu', password='Password123!')
        self.user_finance.roles.add(self.role_finance)

        # Create sample tasks
        now = timezone.now()
        today = now.date()
        self.task_completed_ontime = Task.objects.create(
            title='Completed On-Time Task',
            responsible_department=self.dept_it,
            creator=self.rector,
            status=Task.Status.COMPLETED,
            priority=Task.Priority.HIGH,
            deadline=today + timedelta(days=2),
            completed_at=now,
        )
        TaskAssignment.objects.create(
            task=self.task_completed_ontime, user=self.emp_it, assignment_status=TaskAssignment.AssignmentStatus.APPROVED,
            accepted_at=now - timedelta(days=1),
        )

        self.task_overdue = Task.objects.create(
            title='Overdue Active Task',
            responsible_department=self.dept_it,
            creator=self.rector,
            status=Task.Status.IN_PROGRESS,
            priority=Task.Priority.URGENT,
            deadline=today - timedelta(days=2),
        )
        TaskAssignment.objects.create(
            task=self.task_overdue, user=self.emp_it, assignment_status=TaskAssignment.AssignmentStatus.IN_PROGRESS,
            accepted_at=now - timedelta(days=3),
        )

        self.task_lib = Task.objects.create(
            title='Library Book Indexing',
            responsible_department=self.dept_lib,
            creator=self.vice_rector,
            status=Task.Status.COMPLETED,
            priority=Task.Priority.MEDIUM,
            deadline=today + timedelta(days=5),
            completed_at=now,
        )
        TaskAssignment.objects.create(
            task=self.task_lib, user=self.emp_lib, assignment_status=TaskAssignment.AssignmentStatus.APPROVED,
            accepted_at=now - timedelta(days=2),
        )

        self.task_fin = Task.objects.create(
            title='Finance Audit Q3',
            responsible_department=self.dept_fin,
            creator=self.rector,
            status=Task.Status.IN_PROGRESS,
            priority=Task.Priority.HIGH,
            deadline=today + timedelta(days=10),
        )

    # 1. Executive Dashboard Access & Canonical Routing
    def test_rector_can_access_executive_dashboard(self):
        client = Client()
        client.force_login(self.rector)
        response = client.get(reverse('analytics:executive_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Executive Monitoring')
        self.assertContains(response, 'IT Department')

    def test_canonical_executive_route_url(self):
        self.assertEqual(reverse('analytics:executive_dashboard'), '/analytics/executive/')

    def test_root_analytics_redirects_to_canonical_executive_route(self):
        client = Client()
        client.force_login(self.rector)
        response = client.get('/analytics/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('analytics:executive_dashboard'))

    def test_root_analytics_preserves_query_params_on_redirect(self):
        client = Client()
        client.force_login(self.rector)
        response = client.get('/analytics/?period=7d&department_id=' + str(self.dept_it.id))
        self.assertEqual(response.status_code, 302)
        expected_url = reverse('analytics:executive_dashboard') + f'?period=7d&department_id={self.dept_it.id}'
        self.assertEqual(response.url, expected_url)

    def test_sidebar_uses_canonical_executive_route(self):
        client = Client()
        client.force_login(self.rector)
        response = client.get(reverse('analytics:executive_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/analytics/executive/"')

    def test_vice_rector_sees_only_supervised_departments(self):
        client = Client()
        client.force_login(self.vice_rector)
        response = client.get(reverse('analytics:executive_dashboard'))
        self.assertEqual(response.status_code, 200)
        # Vice rector supervises IT and LIB, but NOT FIN
        self.assertContains(response, 'IT Department')
        self.assertContains(response, 'Library Department')
        self.assertNotContains(response, 'Finance Department')

    def test_department_head_sees_only_own_department_dashboard(self):
        client = Client()
        client.force_login(self.head_it)
        response = client.get(reverse('analytics:department_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'IT Department')
        self.assertNotContains(response, 'Library Department')

    def test_department_head_idor_protection_other_department(self):
        client = Client()
        client.force_login(self.head_it)
        # Attempt to access Library analytics
        response = client.get(reverse('analytics:department_analytics') + f'?department_id={self.dept_lib.id}')
        self.assertEqual(response.status_code, 403)

    def test_employee_redirects_to_personal_analytics(self):
        client = Client()
        client.force_login(self.emp_it)
        response = client.get(reverse('analytics:executive_dashboard'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Personal Performance')
        self.assertContains(response, self.emp_it.username)

    def test_employee_cannot_view_other_employee_analytics(self):
        client = Client()
        client.force_login(self.emp_it)
        # Attempt to access emp_lib analytics
        response = client.get(reverse('analytics:personal_analytics') + f'?employee_id={self.emp_lib.id}')
        self.assertEqual(response.status_code, 403)

    # 2. HR & Payroll Access Scoping
    def test_hr_analytics_access(self):
        client = Client()
        client.force_login(self.user_hr)
        response = client.get(reverse('analytics:hr_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'HR Workforce Analytics')

    def test_non_hr_cannot_access_hr_analytics(self):
        client = Client()
        client.force_login(self.emp_it)
        response = client.get(reverse('analytics:hr_analytics'))
        self.assertEqual(response.status_code, 403)

    def test_finance_payroll_analytics_access(self):
        client = Client()
        client.force_login(self.user_finance)
        response = client.get(reverse('analytics:payroll_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payroll & Compensation Analytics')

    def test_rector_and_heads_cannot_see_individual_salaries_in_analytics(self):
        client = Client()
        client.force_login(self.rector)
        response = client.get(reverse('analytics:executive_dashboard'))
        self.assertEqual(response.status_code, 200)
        # Must not contain individual salary numbers or fields
        self.assertNotContains(response, 'base_salary')
        self.assertNotContains(response, 'gross_salary')
        self.assertNotContains(response, 'net_salary')

    # 3. Superadmin Audit Analytics
    def test_superadmin_can_access_audit_analytics(self):
        client = Client()
        client.force_login(self.superadmin)
        response = client.get(reverse('analytics:audit_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Security & Audit Analytics')

    def test_non_superadmin_cannot_access_audit_analytics(self):
        client = Client()
        client.force_login(self.rector)
        response = client.get(reverse('analytics:audit_analytics'))
        self.assertEqual(response.status_code, 403)

    # 4. Selector & Formula Verifications
    def test_metrics_calculation_formulas(self):
        metrics = get_executive_metrics(self.rector)
        self.assertEqual(metrics['total_tasks'], 4)
        self.assertEqual(metrics['completed_tasks'], 2)
        self.assertEqual(metrics['overdue_tasks'], 1)
        # On-time rate: 2 completed on time / 2 completed = 100%
        self.assertEqual(metrics['ontime_rate'], 100.0)

    def test_department_comparison_data(self):
        dept_data = get_department_comparison_data(self.rector)
        self.assertEqual(len(dept_data), 3)
        it_row = next(d for d in dept_data if d['department_code'] == 'IT')
        self.assertEqual(it_row['total_tasks'], 2)
        self.assertEqual(it_row['completed'], 1)
        self.assertEqual(it_row['overdue'], 1)

    def test_deadline_metrics(self):
        dl = get_deadline_metrics(self.rector)
        self.assertEqual(dl['overdue'], 1)
        self.assertEqual(dl['deadline_compliance_rate'], 100.0)

    def test_bottleneck_metrics(self):
        bm = get_bottleneck_metrics(self.rector)
        self.assertEqual(bm['waiting_employee'], 1)

    def test_employee_personal_metrics(self):
        m = get_employee_personal_metrics(self.emp_it)
        self.assertEqual(m['total_assigned'], 2)
        self.assertEqual(m['completed'], 1)
        self.assertEqual(m['overdue'], 1)
        self.assertEqual(m['ontime_rate'], 100.0)

    # 5. Date Filtering Logic
    def test_parse_date_range_presets(self):
        start, end, label = parse_date_range('7d')
        self.assertEqual(label, 'Last 7 Days')
        self.assertTrue(start < end)

        start, end, label = parse_date_range('custom', '2026-01-01', '2026-01-15')
        self.assertEqual(start.date(), date(2026, 1, 1))
        self.assertEqual(end.date(), date(2026, 1, 15))

    # 6. Report Center & Exports
    def test_report_center_view(self):
        client = Client()
        client.force_login(self.rector)
        response = client.get(reverse('analytics:report_center'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'University Report Center')

    def test_export_university_tasks_pdf(self):
        client = Client()
        client.force_login(self.rector)
        url = reverse('analytics:report_export') + '?report_type=UNIVERSITY_TASKS&format=pdf'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_export_department_performance_excel(self):
        client = Client()
        client.force_login(self.rector)
        url = reverse('analytics:report_export') + '?report_type=DEPARTMENT_PERFORMANCE&format=excel'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response['Content-Type'])

    def test_export_deadline_compliance_csv(self):
        client = Client()
        client.force_login(self.rector)
        url = reverse('analytics:report_export') + '?report_type=DEADLINE_COMPLIANCE&format=csv'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertContains(response, 'Completed Before Deadline')

    def test_unauthorized_payroll_export_denied(self):
        client = Client()
        client.force_login(self.emp_it)
        url = reverse('analytics:report_export') + '?report_type=PAYROLL_ANALYTICS&format=pdf'
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    # 7. Management Healthcheck Command
    def test_analytics_healthcheck_command(self):
        call_command('analytics_healthcheck')
