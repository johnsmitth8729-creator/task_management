from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from core.models import AuditLog, log_audit
from organization.models import Department, Position
from organization.services import assign_department_head, assign_vice_rector_responsibility

User = get_user_model()


class CoreDashboardAndAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.dept = Department.objects.create(name='IT Department', code='IT')
        self.pos = Position.objects.create(name='Developer', code='DEV')

        self.rector = User.objects.create_user(
            username='rector', email='rector@example.com', password='Password123!', is_superuser=True,
        )
        self.rector.roles.add(self.rector_role)

        self.vr = User.objects.create_user(
            username='vr', email='vr@example.com', password='Password123!',
        )
        self.vr.roles.add(self.vr_role)
        assign_vice_rector_responsibility(self.vr, self.dept, actor=self.rector)

        self.head = User.objects.create_user(
            username='head', email='head@example.com', password='Password123!', department=self.dept,
        )
        self.head.roles.add(self.head_role)
        assign_department_head(self.dept, self.head, actor=self.rector)

        self.emp = User.objects.create_user(
            username='emp', email='emp@example.com', password='Password123!', department=self.dept, position=self.pos,
        )
        self.emp.roles.add(self.emp_role)

    def test_anonymous_user_redirected_from_dashboard(self):
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('login'), res.url)

    def test_rector_dashboard_contains_admin_metrics(self):
        self.client.login(username='rector', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'IT Department')
        self.assertIn('active_departments', res.context)
        self.assertIn('total_users', res.context)

    def test_vice_rector_dashboard(self):
        self.client.login(username='vr', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('my_departments', res.context)

    def test_department_head_dashboard(self):
        self.client.login(username='head', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('department_employees', res.context)

    def test_employee_dashboard(self):
        self.client.login(username='emp', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'My Employment Details')


class AuditLogTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.rector = User.objects.create_user(
            username='rector', email='rector@example.com', password='Password123!', is_superuser=True,
        )
        self.rector.roles.add(self.rector_role)

        self.emp = User.objects.create_user(
            username='emp', email='emp@example.com', password='Password123!',
        )
        self.emp.roles.add(self.emp_role)

    def test_log_audit_helper_and_view(self):
        log_entry = log_audit(
            actor=self.rector,
            action=AuditLog.Actions.USER_CREATED,
            target_repr='Test User',
            details={'test': True},
        )
        self.assertEqual(log_entry.action, AuditLog.Actions.USER_CREATED)
        self.assertEqual(log_entry.actor, self.rector)

        # Rector can view audit log list
        self.client.login(username='rector', password='Password123!')
        res = self.client.get(reverse('audit_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Test User')

        # Non-rector blocked with 403
        self.client.login(username='emp', password='Password123!')
        res_blocked = self.client.get(reverse('audit_list'))
        self.assertEqual(res_blocked.status_code, 403)


class LanguageAndAdminRegistrationTests(TestCase):
    def test_configured_languages(self):
        supported_codes = [code for code, name in settings.LANGUAGES]
        self.assertIn('uz', supported_codes)
        self.assertIn('en', supported_codes)
        self.assertIn('ru', supported_codes)

    def test_language_switch_endpoint(self):
        res = self.client.post(
            reverse('set_language'),
            {'language': 'uz', 'next': reverse('login')},
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, 'uz')

    def test_admin_registration(self):
        from django.contrib import admin
        from accounts.models import Role, User
        from core.models import AuditLog
        from organization.models import Department, DepartmentResponsibility, Position

        self.assertIn(Role, admin.site._registry)
        self.assertIn(User, admin.site._registry)
        self.assertIn(Department, admin.site._registry)
        self.assertIn(Position, admin.site._registry)
        self.assertIn(DepartmentResponsibility, admin.site._registry)
        self.assertIn(AuditLog, admin.site._registry)
