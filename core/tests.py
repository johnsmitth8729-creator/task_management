import os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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


class PublicLandingPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')
        self.user = User.objects.create_user(
            username='landing_user', email='landing@test.com', password='Password123!'
        )
        self.user.roles.add(self.emp_role)

    def test_anonymous_user_sees_landing_page(self):
        res = self.client.get(reverse('home'))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'core/landing.html')
        self.assertContains(res, 'TASK MANAGEMENT')
        self.assertContains(res, 'Al-Khwarizmi University')
        self.assertContains(res, 'Login to Platform')
        self.assertContains(res, reverse('login'))
        self.assertContains(res, 'logo-dark-variant')
        self.assertContains(res, 'logo-light-variant')
        self.assertContains(res, 'toggleAppTheme()')

    def test_authenticated_user_redirected_to_dashboard(self):
        self.client.login(username='landing_user', password='Password123!')
        res = self.client.get(reverse('home'))
        self.assertRedirects(res, reverse('dashboard'))

    def test_login_url_accessible_directly(self):
        res = self.client.get(reverse('login'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Sign In')

    def test_landing_page_uzbek_localization(self):
        res = self.client.get('/uz/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Al-Xorazmiy Universiteti")
        self.assertContains(res, "Tizimga kirish")


class ErrorPagesTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_400_error_page(self):
        res = self.client.get(reverse('error_400'))
        self.assertEqual(res.status_code, 400)
        self.assertTemplateUsed(res, '400.html')
        self.assertContains(res, '400', status_code=400)
        self.assertContains(res, 'Bad Request', status_code=400)

    def test_403_error_page(self):
        res = self.client.get(reverse('error_403'))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, '403.html')
        self.assertContains(res, '403', status_code=403)
        self.assertContains(res, 'Access Denied', status_code=403)

    def test_404_error_page(self):
        res = self.client.get(reverse('error_404'))
        self.assertEqual(res.status_code, 404)
        self.assertTemplateUsed(res, '404.html')
        self.assertContains(res, '404', status_code=404)
        self.assertContains(res, 'Page Not Found', status_code=404)

    def test_500_error_page(self):
        res = self.client.get(reverse('error_500'))
        self.assertEqual(res.status_code, 500)
        self.assertTemplateUsed(res, '500.html')
        self.assertContains(res, '500', status_code=500)
        self.assertContains(res, 'Server Error', status_code=500)

    def test_nonexistent_url_with_custom_handler(self):
        # Trigger custom 404 handler directly
        from core.views import custom_404
        from django.test import RequestFactory
        factory = RequestFactory()
        req = factory.get('/some-nonexistent-url-path-xyz-123/')
        res = custom_404(req)
        self.assertEqual(res.status_code, 404)
        self.assertIn(b'404', res.content)

    def test_invalid_url_renders_custom_404_page(self):
        res = self.client.get('/departments/s')
        self.assertEqual(res.status_code, 404)
        self.assertContains(res, '404', status_code=404)
        self.assertContains(res, 'Page Not Found', status_code=404)


class RoleSecurityAndIDORAuditTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Head')
        self.hr_role = Role.objects.create(code=Role.Codes.HR, name='HR Manager')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.it_dept = Department.objects.create(name='IT Department', code='IT')
        self.lib_dept = Department.objects.create(name='Library', code='LIB')

        self.superadmin = User.objects.create_user(
            username='superadmin', email='superadmin@test.com', password='Password123!', is_staff=True, is_superuser=True
        )
        self.rector = User.objects.create_user(
            username='rector', email='rector@test.com', password='Password123!', is_staff=False, is_superuser=False
        )
        self.rector.roles.add(self.rector_role)

        self.vr = User.objects.create_user(username='vr', email='vr@test.com', password='Password123!')
        self.vr.roles.add(self.vr_role)
        assign_vice_rector_responsibility(self.vr, self.it_dept, actor=self.superadmin)

        self.dept_head = User.objects.create_user(
            username='dept_head', email='head@test.com', password='Password123!', department=self.it_dept
        )
        self.dept_head.roles.add(self.head_role)
        assign_department_head(self.it_dept, self.dept_head, actor=self.superadmin)

        self.hr_user = User.objects.create_user(
            username='hr_user', email='hr@test.com', password='Password123!', department=self.it_dept
        )
        self.hr_user.roles.add(self.hr_role)

        self.emp = User.objects.create_user(
            username='emp', email='emp@test.com', password='Password123!', department=self.it_dept
        )
        self.emp.roles.add(self.emp_role)

    def test_rector_cannot_access_django_admin(self):
        self.client.login(username='rector', password='Password123!')
        res = self.client.get('/admin/')
        # Django admin redirects non-staff users to admin login
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login/', res.url)

    def test_superadmin_can_access_django_admin(self):
        self.client.login(username='superadmin', password='Password123!')
        res = self.client.get('/admin/')
        self.assertEqual(res.status_code, 200)

    def test_employee_cannot_access_hr_permissions(self):
        self.client.login(username='emp', password='Password123!')
        res = self.client.get(reverse('hr:permissions_config'))
        self.assertEqual(res.status_code, 403)

    def test_employee_cannot_create_employee(self):
        self.client.login(username='emp', password='Password123!')
        res = self.client.get(reverse('hr:employee_create'))
        self.assertEqual(res.status_code, 403)

    def test_employee_cannot_access_kpi_catalog(self):
        self.client.login(username='emp', password='Password123!')
        res = self.client.get(reverse('kpi:definition_list'))
        self.assertEqual(res.status_code, 403)

    def test_employee_cannot_access_dept_dashboard(self):
        self.client.login(username='emp', password='Password123!')
        res = self.client.get(reverse('dept_dashboard'))
        self.assertEqual(res.status_code, 403)

    def test_department_head_cannot_access_other_department_detail(self):
        self.client.login(username='dept_head', password='Password123!')
        res = self.client.get(reverse('department_detail', kwargs={'pk': self.lib_dept.pk}))
        self.assertEqual(res.status_code, 403)

    def test_department_head_cannot_access_hr_permissions(self):
        self.client.login(username='dept_head', password='Password123!')
        res = self.client.get(reverse('hr:permissions_config'))
        self.assertEqual(res.status_code, 403)

    def test_vice_rector_cannot_access_unassigned_department(self):
        self.client.login(username='vr', password='Password123!')
        res = self.client.get(reverse('department_detail', kwargs={'pk': self.lib_dept.pk}))
        self.assertEqual(res.status_code, 403)

    def test_hr_cannot_access_second_approval_center(self):
        self.client.login(username='hr_user', password='Password123!')
        res = self.client.get(reverse('management_second_approval'))
        self.assertEqual(res.status_code, 403)


class Phase15ProductionHardeningTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.role_emp = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')
        self.user = User.objects.create_user(
            username='search_user',
            email='search_user@example.com',
            password='Password123!',
        )
        self.user.roles.add(self.role_emp)

    def test_liveness_probe_returns_200(self):
        res = self.client.get(reverse('health_live'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content.decode(), "OK")

    def test_readiness_probe_returns_200_when_db_ready(self):
        res = self.client.get(reverse('health_ready'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content.decode(), "READY")

    def test_health_check_json_endpoint(self):
        res = self.client.get(reverse('health_check'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get('status'), 'HEALTHY')
        self.assertIn('components', data)
        self.assertIn('database', data['components'])

    def test_health_check_browser_html_dashboard(self):
        # Browser request with Accept: text/html renders HTML dashboard
        res = self.client.get(reverse('health_check'), HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/html', res.headers.get('Content-Type', ''))
        self.assertTemplateUsed(res, 'core/system_health.html')
        self.assertContains(res, 'System Health & Diagnostics')
        self.assertContains(res, 'Database Engine')
        self.assertContains(res, 'Cache Subsystem')

    def test_health_check_explicit_format_override(self):
        # Explicit ?format=json returns JSON even if browser sends text/html
        res_json = self.client.get(reverse('health_check') + '?format=json', HTTP_ACCEPT='text/html')
        self.assertEqual(res_json.status_code, 200)
        self.assertIn('application/json', res_json.headers.get('Content-Type', ''))
        self.assertEqual(res_json.json().get('status'), 'HEALTHY')

        # Explicit ?format=html returns HTML template
        res_html = self.client.get(reverse('health_check') + '?format=html')
        self.assertEqual(res_html.status_code, 200)
        self.assertIn('text/html', res_html.headers.get('Content-Type', ''))


    def test_security_headers_middleware_applied(self):
        res = self.client.get(reverse('health_live'))
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res.headers.get('X-Frame-Options'), 'DENY')
        self.assertIn("default-src 'self'", res.headers.get('Content-Security-Policy', ''))

    def test_global_search_authenticated(self):
        self.client.login(username='search_user', password='Password123!')
        res = self.client.get(reverse('global_search') + '?q=test')
        self.assertEqual(res.status_code, 200)
        self.assertIn('search_query', res.context)

    def test_production_readiness_command_executes(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('production_readiness_check', stdout=out)
        output = out.getvalue()
        self.assertIn('UNIVERSITY TASK MANAGEMENT PLATFORM', output)
        self.assertIn('Readiness Score', output)

    def test_backup_database_command_executes(self):
        import tempfile
        from django.core.management import call_command
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmpdir:
            out = StringIO()
            call_command('backup_database', output_dir=tmpdir, stdout=out)
            output = out.getvalue()
            self.assertIn('Backup successfully completed', output)
            files = os.listdir(tmpdir)
            self.assertTrue(any(f.endswith('.json') for f in files))
            self.assertTrue(any(f.endswith('_meta.json') for f in files))


class UnifiedNavigationArchitectureTests(TestCase):
    """
    Tests for the centralized enterprise navigation registry (core/navigation.py)
    and the unified sidebar navigation across all university roles.
    """
    def setUp(self):
        self.client = Client()
        self.rector_role, _ = Role.objects.get_or_create(code=Role.Codes.RECTOR, defaults={'name': 'Rector'})
        self.vr_role, _ = Role.objects.get_or_create(code=Role.Codes.VICE_RECTOR, defaults={'name': 'Vice Rector'})
        self.head_role, _ = Role.objects.get_or_create(code=Role.Codes.DEPARTMENT_HEAD, defaults={'name': 'Department Head'})
        self.hr_role, _ = Role.objects.get_or_create(code=Role.Codes.HR, defaults={'name': 'HR Officer'})
        self.finance_role, _ = Role.objects.get_or_create(code=Role.Codes.FINANCE, defaults={'name': 'Finance Officer'})
        self.emp_role, _ = Role.objects.get_or_create(code=Role.Codes.EMPLOYEE, defaults={'name': 'Employee'})

        self.dept, _ = Department.objects.get_or_create(code='CS', defaults={'name': 'Computer Science'})

        # Users
        self.superadmin = User.objects.create_user(
            username='admin_nav', email='admin_nav@univ.uz', password='Password123!', is_superuser=True, is_staff=True
        )

        self.rector = User.objects.create_user(
            username='rector_nav', email='rector_nav@univ.uz', password='Password123!'
        )
        self.rector.roles.add(self.rector_role)

        self.vr = User.objects.create_user(
            username='vr_nav', email='vr_nav@univ.uz', password='Password123!'
        )
        self.vr.roles.add(self.vr_role)
        assign_vice_rector_responsibility(self.vr, self.dept, actor=self.superadmin)

        self.head = User.objects.create_user(
            username='head_nav', email='head_nav@univ.uz', password='Password123!', department=self.dept
        )
        self.head.roles.add(self.head_role)
        assign_department_head(self.dept, self.head, actor=self.superadmin)

        self.hr = User.objects.create_user(
            username='hr_nav', email='hr_nav@univ.uz', password='Password123!'
        )
        self.hr.roles.add(self.hr_role)

        self.finance = User.objects.create_user(
            username='finance_nav', email='finance_nav@univ.uz', password='Password123!'
        )
        self.finance.roles.add(self.finance_role)

        self.employee = User.objects.create_user(
            username='emp_nav', email='emp_nav@univ.uz', password='Password123!', department=self.dept
        )
        self.employee.roles.add(self.emp_role)

    def test_01_anonymous_user_has_no_navigation(self):
        from core.context_processors import navigation_context
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        factory = RequestFactory()
        req = factory.get(reverse('login'))
        req.user = AnonymousUser()
        ctx = navigation_context(req)
        self.assertEqual(ctx['sidebar_navigation_groups'], [])
        self.assertEqual(ctx['sidebar_sections'], [])
        self.assertEqual(ctx['contextual_navigation_items'], [])
        self.assertIsNone(ctx['active_navigation_section'])

    def test_02_all_authorized_users_see_dashboard(self):
        users = [self.superadmin, self.rector, self.vr, self.head, self.hr, self.finance, self.employee]
        for user in users:
            self.client.force_login(user)
            res = self.client.get(reverse('dashboard'))
            self.assertEqual(res.status_code, 200)
            section_ids = [s['id'] for s in res.context['sidebar_sections']]
            self.assertIn('main', section_ids, f"User {user.username} missing main section")
            active_sec = res.context['active_navigation_section']
            self.assertIsNotNone(active_sec)
            self.assertEqual(active_sec['id'], 'main')

    def test_03_employee_sees_only_authorized_sections(self):
        self.client.login(username='emp_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        section_ids = [s['id'] for s in res.context['sidebar_sections']]

        self.assertIn('main', section_ids)
        self.assertIn('tasks', section_ids)
        self.assertIn('documents', section_ids)
        self.assertIn('performance', section_ids)
        self.assertIn('payroll', section_ids)
        self.assertIn('communication', section_ids)
        self.assertIn('operations', section_ids)
        self.assertIn('ai', section_ids)

        # Employee MUST NOT see Superadmin, HR, Organization, Automation
        self.assertNotIn('admin', section_ids)
        self.assertNotIn('hr', section_ids)
        self.assertNotIn('organization', section_ids)
        self.assertNotIn('automation', section_ids)

    def test_04_dept_head_sees_authorized_sections(self):
        self.client.login(username='head_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        section_ids = [s['id'] for s in res.context['sidebar_sections']]

        self.assertIn('tasks', section_ids)
        self.assertIn('organization', section_ids)

        # Dept Head tasks items: must have approvals hub and dept task list
        tasks_group = next(s for s in res.context['sidebar_navigation_groups'] if s['id'] == 'tasks')
        item_ids = [it['id'] for it in tasks_group['items']]
        self.assertIn('approvals_hub', item_ids)
        self.assertIn('dept_task_list', item_ids)

    def test_05_vice_rector_sees_authorized_sections(self):
        self.client.login(username='vr_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        section_ids = [s['id'] for s in res.context['sidebar_sections']]

        self.assertIn('tasks', section_ids)
        self.assertIn('organization', section_ids)

        # Vice Rector tasks items: must have approvals hub, but not dept task list
        tasks_group = next(s for s in res.context['sidebar_navigation_groups'] if s['id'] == 'tasks')
        item_ids = [it['id'] for it in tasks_group['items']]
        self.assertIn('approvals_hub', item_ids)
        self.assertNotIn('dept_task_list', item_ids)

    def test_06_rector_sees_authorized_sections_executive_only(self):
        self.client.login(username='rector_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        section_ids = [s['id'] for s in res.context['sidebar_sections']]

        self.assertIn('tasks', section_ids)
        self.assertIn('organization', section_ids)
        self.assertIn('hr', section_ids)
        self.assertIn('performance', section_ids)
        self.assertNotIn('admin', section_ids)

        # Rector does NOT receive tasks as an employee executor
        tasks_group = next(s for s in res.context['sidebar_navigation_groups'] if s['id'] == 'tasks')
        item_ids = [it['id'] for it in tasks_group['items']]
        self.assertNotIn('employee_incoming', item_ids)

    def test_07_hr_sees_authorized_sections(self):
        self.client.login(username='hr_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        section_ids = [s['id'] for s in res.context['sidebar_sections']]
        self.assertIn('hr', section_ids)
        self.assertNotIn('admin', section_ids)

    def test_08_finance_sees_authorized_sections(self):
        self.client.login(username='finance_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        section_ids = [s['id'] for s in res.context['sidebar_sections']]
        self.assertIn('payroll', section_ids)
        payroll_group = next(s for s in res.context['sidebar_navigation_groups'] if s['id'] == 'payroll')
        item_ids = [it['id'] for it in payroll_group['items']]
        self.assertIn('payroll_periods', item_ids)
        self.assertIn('payroll_records', item_ids)

    def test_09_superadmin_sees_system_administration(self):
        self.client.login(username='admin_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        section_ids = [s['id'] for s in res.context['sidebar_sections']]
        self.assertIn('admin', section_ids)
        admin_group = next(s for s in res.context['sidebar_navigation_groups'] if s['id'] == 'admin')
        admin_item_ids = [it['id'] for it in admin_group['items']]
        self.assertIn('admin_django', admin_item_ids)
        self.assertIn('admin_health', admin_item_ids)
        self.assertIn('admin_audit', admin_item_ids)

    def test_10_unauthorized_sections_are_hidden(self):
        self.client.login(username='emp_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        section_ids = [s['id'] for s in res.context['sidebar_sections']]
        self.assertNotIn('admin', section_ids)
        self.assertNotIn('hr', section_ids)

    def test_11_unauthorized_child_items_are_hidden(self):
        self.client.login(username='emp_nav', password='Password123!')
        res = self.client.get(reverse('employee_incoming'))
        self.assertEqual(res.status_code, 200)
        contextual_ids = [it['id'] for it in res.context['contextual_navigation_items']]
        self.assertNotIn('dept_task_list', contextual_ids)

    def test_12_no_empty_contextual_navigation_groups(self):
        users = [self.superadmin, self.rector, self.vr, self.head, self.hr, self.finance, self.employee]
        for user in users:
            self.client.force_login(user)
            res = self.client.get(reverse('dashboard'))
            for group in res.context['sidebar_navigation_groups']:
                self.assertGreater(len(group['items']), 0, f"Group {group['id']} is empty for {user.username}")

    def test_13_active_section_detection(self):
        self.client.login(username='emp_nav', password='Password123!')
        res = self.client.get(reverse('employee_incoming'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context['active_navigation_section']
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'tasks')

    def test_14_active_child_detection(self):
        self.client.login(username='emp_nav', password='Password123!')
        res = self.client.get(reverse('employee_incoming'))
        self.assertEqual(res.status_code, 200)
        incoming_item = next((it for it in res.context['contextual_navigation_items'] if it['id'] == 'employee_incoming'), None)
        self.assertIsNotNone(incoming_item)
        self.assertTrue(incoming_item['is_active'])

    def test_15_contextual_navigation_uses_existing_urls(self):
        self.client.login(username='admin_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        for group in res.context['sidebar_navigation_groups']:
            for item in group['items']:
                self.assertTrue(item['url'].startswith('/'), f"Item {item['id']} has invalid url: {item['url']}")

    def test_16_no_duplicate_navigation_entries(self):
        from core.navigation import build_navigation_registry
        groups = build_navigation_registry()
        group_ids = [g.id for g in groups]
        self.assertEqual(len(group_ids), len(set(group_ids)), "Duplicate group IDs in registry")
        for g in groups:
            item_ids = [it.id for it in g.items]
            self.assertEqual(len(item_ids), len(set(item_ids)), f"Duplicate item IDs in group {g.id}")

    def test_17_english_navigation_renders(self):
        self.client.login(username='emp_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'), HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Dashboard')
        self.assertContains(res, 'Tasks &amp; Execution')

    def test_18_uzbek_language_navigation_translation(self):
        self.client.login(username='emp_nav', password='Password123!')
        res = self.client.get('/uz/dashboard/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Topshiriqlar va ijro')
        self.assertContains(res, 'Boshqaruv paneli')

    def test_19_existing_task_execution_access_for_dept_head_remains(self):
        self.client.login(username='head_nav', password='Password123!')
        res_incoming = self.client.get(reverse('employee_incoming'))
        self.assertEqual(res_incoming.status_code, 200)
        res_dash = self.client.get(reverse('employee_dashboard'))
        self.assertEqual(res_dash.status_code, 200)

    def test_20_existing_task_execution_access_for_vice_rector_remains(self):
        self.client.login(username='vr_nav', password='Password123!')
        res_incoming = self.client.get(reverse('employee_incoming'))
        self.assertEqual(res_incoming.status_code, 200)
        res_dash = self.client.get(reverse('employee_dashboard'))
        self.assertEqual(res_dash.status_code, 200)

    def test_21_rector_is_not_incorrectly_converted_into_executor(self):
        self.client.login(username='rector_nav', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        tasks_group = next(s for s in res.context['sidebar_navigation_groups'] if s['id'] == 'tasks')
        item_ids = [it['id'] for it in tasks_group['items']]
        self.assertNotIn('employee_incoming', item_ids)
        self.assertNotIn('employee_dashboard', item_ids)

    def test_22_payroll_visibility_remains_unchanged(self):
        # Ordinary employee
        self.client.login(username='emp_nav', password='Password123!')
        res_emp = self.client.get(reverse('dashboard'))
        payroll_group_emp = next(s for s in res_emp.context['sidebar_navigation_groups'] if s['id'] == 'payroll')
        emp_items = [it['id'] for it in payroll_group_emp['items']]
        self.assertEqual(emp_items, ['my_salary', 'my_payslips'])
        self.assertEqual(payroll_group_emp['landing_url'], reverse('payroll:my_salary'))

        # Finance user
        self.client.login(username='finance_nav', password='Password123!')
        res_fin = self.client.get(reverse('dashboard'))
        payroll_group_fin = next(s for s in res_fin.context['sidebar_navigation_groups'] if s['id'] == 'payroll')
        fin_items = [it['id'] for it in payroll_group_fin['items']]
        self.assertIn('payroll_periods', fin_items)
        self.assertIn('payroll_records', fin_items)

    def test_23_system_admin_remains_superadmin_only(self):
        # Rector is not superadmin -> no admin section
        self.client.login(username='rector_nav', password='Password123!')
        res_rector = self.client.get(reverse('dashboard'))
        sec_ids = [s['id'] for s in res_rector.context['sidebar_sections']]
        self.assertNotIn('admin', sec_ids)

        # Superadmin has admin section
        self.client.login(username='admin_nav', password='Password123!')
        res_admin = self.client.get(reverse('dashboard'))
        admin_sec_ids = [s['id'] for s in res_admin.context['sidebar_sections']]
        self.assertIn('admin', admin_sec_ids)


class ActiveYearTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='year_user', email='year@test.com', password='Password123!',
            is_superuser=True
        )

    def test_active_year_context_default(self):
        self.client.login(username='year_user', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('active_year', res.context)
        self.assertIn('available_years', res.context)
        self.assertEqual(res.context['active_year'], timezone.now().year)

    def test_set_active_year_post(self):
        self.client.login(username='year_user', password='Password123!')
        target_year = 2025
        res = self.client.post(
            reverse('set_active_year'),
            {'year': target_year, 'next': reverse('dashboard')},
            follow=True
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['active_year'], 2025)
        self.assertTrue(res.context['is_historical_year'])
        self.assertEqual(self.client.session['active_year'], 2025)

    def test_navbar_and_modal_rendered_with_calendar_button(self):
        self.client.login(username='year_user', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        # Calendar modal trigger and year modal in page
        self.assertContains(res, 'yearSelectModal')
        self.assertContains(res, 'bi-calendar3')
        # Check that Ishchi yil / My Profile / Logout are in the HTML
        self.assertContains(res, 'My Profile')
        self.assertContains(res, 'Logout')

    def test_dashboard_task_stats_scoped_to_active_year(self):
        from tasks.models import Task
        # Create a task for current year
        Task.objects.create(
            title="Task Current Year",
            creator=self.user,
            deadline=timezone.now().date(),
        )
        self.client.login(username='year_user', password='Password123!')

        # When active_year is current year
        res_current = self.client.get(reverse('dashboard'))
        self.assertEqual(res_current.context['task_stats']['total'], 1)

        # Switch to 2025 (empty/past year)
        self.client.post(reverse('set_active_year'), {'year': 2025, 'next': reverse('dashboard')}, follow=True)
        res_past = self.client.get(reverse('dashboard'))
        self.assertEqual(res_past.context['task_stats']['total'], 0)

        # Switch back to current year -> preserved!
        self.client.post(reverse('set_active_year'), {'year': timezone.now().year, 'next': reverse('dashboard')}, follow=True)
        res_back = self.client.get(reverse('dashboard'))
        self.assertEqual(res_back.context['task_stats']['total'], 1)


class UnifiedNavigationRefactorTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.superuser = User.objects.create_superuser(
            username='admin_boss', email='admin_boss@example.test', password='Password123!',
        )
        self.vr = User.objects.create_user(
            username='vr_user', email='vr_user@example.test', password='Password123!',
        )
        self.vr.roles.add(self.vr_role)
        self.dept = Department.objects.create(name='Computer Science', code='CS')
        assign_vice_rector_responsibility(self.vr, self.dept, actor=self.superuser)

    def test_superadmin_can_see_add_department_and_access_create_view(self):
        self.client.login(username='admin_boss', password='Password123!')
        res_list = self.client.get(reverse('department_list'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, reverse('department_create'))
        self.assertContains(res_list, 'Add Department')

        res_create = self.client.get(reverse('department_create'))
        self.assertEqual(res_create.status_code, 200)

    def test_responsibility_delete_confirmation_attribute(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('responsibility_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'onsubmit="return confirm(')

    def test_operations_documents_activates_documents_section_not_operations(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('operations:document_list'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context.get('active_navigation_section')
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'documents')
        self.assertIn(str(active_sec['label']), ['Documents & Reports', 'Hujjatlar va hisobotlar'])
        item_ids = [it['id'] for it in res.context.get('contextual_navigation_items', [])]
        self.assertIn('official_documents', item_ids)
        self.assertNotIn('service_catalog', item_ids)

    def test_operations_services_activates_operations_section(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('operations:service_catalog'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context.get('active_navigation_section')
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'operations')
        self.assertIn(str(active_sec['label']), ['Operations & Services', 'Xizmatlar va arizalar'])
        item_ids = [it['id'] for it in res.context.get('contextual_navigation_items', [])]
        self.assertIn('service_catalog', item_ids)
        self.assertNotIn('official_documents', item_ids)

    def test_users_list_activates_organization_section_not_admin(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('user_list'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context.get('active_navigation_section')
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'organization')
        self.assertIn(str(active_sec['label']), ['Organization', 'Tashkilot'])
        item_ids = [it['id'] for it in res.context.get('contextual_navigation_items', [])]
        self.assertIn('staff_list', item_ids)
        self.assertNotIn('admin_audit', item_ids)

    def test_automation_dashboard_activates_automation_section_not_main(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('automation:dashboard'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context.get('active_navigation_section')
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'automation')
        self.assertIn(str(active_sec['label']), ['Automation & SLA', 'Avtomatlashtirish va SLA'])
        item_ids = [it['id'] for it in res.context.get('contextual_navigation_items', [])]
        self.assertIn('automation_hub', item_ids)

    def test_payroll_dashboard_activates_payroll_section_not_main(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('payroll:dashboard'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context.get('active_navigation_section')
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'payroll')
        self.assertIn(str(active_sec['label']), ['Payroll & Compensation', 'Ish haqi va kompensatsiya'])
        item_ids = [it['id'] for it in res.context.get('contextual_navigation_items', [])]
        self.assertIn('payroll_dashboard', item_ids)

    def test_performance_dashboard_activates_performance_section_not_main(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('kpi:dashboard'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context.get('active_navigation_section')
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'performance')
        self.assertIn(str(active_sec['label']), ['Performance & KPI', 'Samaradorlik va KPI'])
        item_ids = [it['id'] for it in res.context.get('contextual_navigation_items', [])]
        self.assertIn('kpi_dashboard', item_ids)

    def test_main_dashboard_activates_main_section(self):
        self.client.login(username='admin_boss', password='Password123!')
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        active_sec = res.context.get('active_navigation_section')
        self.assertIsNotNone(active_sec)
        self.assertEqual(active_sec['id'], 'main')
        self.assertIn(str(active_sec['label']), ['Main', 'Asosiy'])


@override_settings(ALLOWED_HOSTS=['*'])
class TaskBadgeAndPaginationTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        self.dept = Department.objects.create(name='IT Dept', code='IT_TEST')
        self.user = User.objects.create_superuser(
            username='super_badge_user',
            email='badge_user@example.com',
            password='Password123!',
        )
        self.other_user = User.objects.create_user(
            username='other_badge_user',
            email='other@example.com',
            password='Password123!',
        )

    def test_badge_counts_and_seen_logic(self):
        from tasks.models import Task
        from core.navigation import _tasks_under_control_badge

        self.client.login(username='super_badge_user', password='Password123!')
        res_init = self.client.get(reverse('dashboard'))
        request = res_init.wsgi_request
        request.session = self.client.session
        request.user = self.user

        baseline = _tasks_under_control_badge(request)
        base_count = baseline['count'] if baseline else 0

        # Create 2 assigned tasks (under control)
        t1 = Task.objects.create(
            title="Control Task 1",
            creator=self.user,
            status=Task.Status.ASSIGNED,
            deadline=timezone.now().date() + timezone.timedelta(days=2),
        )
        t2 = Task.objects.create(
            title="Control Task 2",
            creator=self.user,
            status=Task.Status.IN_PROGRESS,
            deadline=timezone.now().date() + timezone.timedelta(days=3),
        )
        # Create 1 draft/created task by other user (should NOT be counted in under_control)
        Task.objects.create(
            title="Other Created Task",
            creator=self.other_user,
            status=Task.Status.CREATED,
            deadline=timezone.now().date() + timezone.timedelta(days=5),
        )

        control_badge = _tasks_under_control_badge(request)
        self.assertIsNotNone(control_badge)
        self.assertEqual(control_badge['count'], base_count + 2)

        # Now view individual task detail for t1
        res_detail = self.client.get(reverse('task_detail', kwargs={'pk': t1.pk}))
        self.assertEqual(res_detail.status_code, 200)

        # Session should now contain t1 in seen_control_tasks, badge becomes base_count + 1
        request.session = self.client.session
        control_badge_after = _tasks_under_control_badge(request)
        self.assertIsNotNone(control_badge_after)
        self.assertEqual(control_badge_after['count'], base_count + 1)

        # Now mark t2 as seen in session as well
        session = self.client.session
        seen_list = session.get('seen_control_tasks', [])
        seen_list.append(str(t2.pk))
        session['seen_control_tasks'] = seen_list
        session.save()

        request.session = self.client.session
        control_badge_final = _tasks_under_control_badge(request)
        self.assertEqual(
            control_badge_final['count'] if control_badge_final else 0,
            base_count
        )

    def test_overdue_badge_seen_logic(self):
        from tasks.models import Task
        from core.navigation import _overdue_tasks_badge

        self.client.login(username='super_badge_user', password='Password123!')
        res_init = self.client.get(reverse('dashboard'))
        request = res_init.wsgi_request
        request.session = self.client.session
        request.user = self.user

        baseline = _overdue_tasks_badge(request)
        base_count = baseline['count'] if baseline else 0

        t_overdue = Task.objects.create(
            title="Overdue Task",
            creator=self.user,
            status=Task.Status.ASSIGNED,
            deadline=timezone.now().date() - timezone.timedelta(days=2),
        )

        overdue_badge = _overdue_tasks_badge(request)
        self.assertIsNotNone(overdue_badge)
        self.assertEqual(overdue_badge['count'], base_count + 1)

        # View the overdue task detail
        res_detail = self.client.get(reverse('task_detail', kwargs={'pk': t_overdue.pk}))
        self.assertEqual(res_detail.status_code, 200)

        request.session = self.client.session
        overdue_badge_after = _overdue_tasks_badge(request)
        self.assertEqual(
            overdue_badge_after['count'] if overdue_badge_after else 0,
            base_count
        )

    def test_task_list_pagination_20_items_and_numbered_links(self):
        from tasks.models import Task

        for i in range(25):
            Task.objects.create(
                title=f"Bulk Task {i+1}",
                creator=self.user,
                status=Task.Status.ASSIGNED,
                deadline=timezone.now().date() + timezone.timedelta(days=1),
            )

        self.client.login(username='super_badge_user', password='Password123!')
        res = self.client.get(reverse('task_list') + '?status=ASSIGNED')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context['is_paginated'])
        self.assertEqual(len(res.context['tasks']), 20)
        self.assertGreaterEqual(res.context['paginator'].num_pages, 2)
        # Check that page 2 link is present and preserves query params
        self.assertContains(res, 'page=2&status=ASSIGNED')










