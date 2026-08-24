import uuid
from django.contrib.auth import authenticate, get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from organization.models import Department, Position
from organization.services import assign_department_head, assign_vice_rector_responsibility

User = get_user_model()


class UserModelAndRoleTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='IT', code='IT')
        self.pos = Position.objects.create(name='Developer', code='DEV')
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

    def test_custom_user_creation_and_properties(self):
        user = User.objects.create_user(
            username='johndoe',
            email='john@example.com',
            password='SecretPassword123!',
            first_name='John',
            last_name='Doe',
            department=self.dept,
            position=self.pos,
        )
        user.roles.add(self.emp_role)

        self.assertIsInstance(user.id, uuid.UUID)
        self.assertEqual(user.display_name, 'John Doe')
        self.assertEqual(user.initials, 'JD')
        self.assertTrue(user.is_employee)
        self.assertFalse(user.is_rector)
        self.assertFalse(user.is_vice_rector)
        self.assertFalse(user.is_department_head)
        self.assertEqual(user.primary_role, self.emp_role)

    def test_password_is_hashed(self):
        user = User.objects.create_user(
            username='janedoe', email='jane@example.com', password='Password123!',
        )
        self.assertNotEqual(user.password, 'Password123!')
        self.assertTrue(user.check_password('Password123!'))
        self.assertFalse(user.check_password('Wrong!'))

    def test_inactive_user_cannot_authenticate(self):
        User.objects.create_user(
            username='inactiveuser', email='inactive@example.com', password='Password123!', is_active=False,
        )
        self.assertIsNone(authenticate(username='inactiveuser', password='Password123!'))


class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='authuser', email='auth@example.com', password='Password123!', first_name='Auth', last_name='User',
        )

    def test_successful_login_and_logout(self):
        res = self.client.post(
            reverse('login'),
            {'username': 'authuser', 'password': 'Password123!'},
            follow=True,
        )
        self.assertTrue(res.context['user'].is_authenticated)
        self.assertRedirects(res, reverse('dashboard'))

        res_logout = self.client.post(reverse('logout'), follow=True)
        self.assertFalse(res_logout.context['user'].is_authenticated)
        self.assertRedirects(res_logout, reverse('login'))

    def test_wrong_credentials_rejected(self):
        res = self.client.post(
            reverse('login'),
            {'username': 'authuser', 'password': 'WrongPassword!'},
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context['user'].is_authenticated)

    def test_remember_me_session_expiry(self):
        client_no_remember = Client()
        client_no_remember.post(
            reverse('login'),
            {'username': 'authuser', 'password': 'Password123!', 'remember_me': False},
        )
        self.assertTrue(client_no_remember.session.get_expire_at_browser_close())

        client_remember = Client()
        client_remember.post(
            reverse('login'),
            {'username': 'authuser', 'password': 'Password123!', 'remember_me': True},
        )
        self.assertFalse(client_remember.session.get_expire_at_browser_close())


class UserDirectoryAndRBACSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.rector_role = Role.objects.create(code=Role.Codes.RECTOR, name='Rector')
        self.vr_role = Role.objects.create(code=Role.Codes.VICE_RECTOR, name='Vice Rector')
        self.head_role = Role.objects.create(code=Role.Codes.DEPARTMENT_HEAD, name='Head')
        self.emp_role = Role.objects.create(code=Role.Codes.EMPLOYEE, name='Employee')

        self.dept_it = Department.objects.create(name='IT Department', code='IT')
        self.dept_fin = Department.objects.create(name='Finance Department', code='FIN')

        self.rector = User.objects.create_user(
            username='rector', email='rector@example.com', password='Password123!', is_superuser=True,
        )
        self.rector.roles.add(self.rector_role)

        self.vr_acad = User.objects.create_user(
            username='vr.acad', email='vr.acad@example.com', password='Password123!',
        )
        self.vr_acad.roles.add(self.vr_role)
        assign_vice_rector_responsibility(self.vr_acad, self.dept_it, actor=self.rector)

        self.head_it = User.objects.create_user(
            username='head.it', email='head.it@example.com', password='Password123!', department=self.dept_it,
        )
        self.head_it.roles.add(self.head_role)

        self.emp_it = User.objects.create_user(
            username='emp.it', email='emp.it@example.com', password='Password123!', department=self.dept_it,
        )
        self.emp_it.roles.add(self.emp_role)

        self.emp_fin = User.objects.create_user(
            username='emp.fin', email='emp.fin@example.com', password='Password123!', department=self.dept_fin,
        )
        self.emp_fin.roles.add(self.emp_role)

    def test_user_list_scoping_per_role(self):
        # 1. Rector sees all
        self.client.login(username='rector', password='Password123!')
        res_rector = self.client.get(reverse('user_list'))
        self.assertEqual(res_rector.status_code, 200)
        self.assertContains(res_rector, 'emp.it')
        self.assertContains(res_rector, 'emp.fin')

        # 2. Vice Rector sees IT employees, but NOT finance
        self.client.login(username='vr.acad', password='Password123!')
        res_vr = self.client.get(reverse('user_list'))
        self.assertEqual(res_vr.status_code, 200)
        self.assertContains(res_vr, 'emp.it')
        self.assertNotContains(res_vr, 'emp.fin')

        # 3. Dept Head sees own department employees only
        self.client.login(username='head.it', password='Password123!')
        res_head = self.client.get(reverse('user_list'))
        self.assertEqual(res_head.status_code, 200)
        self.assertContains(res_head, 'emp.it')
        self.assertNotContains(res_head, 'emp.fin')

        # 4. Standard employee cannot view user directory (403 Forbidden)
        self.client.login(username='emp.it', password='Password123!')
        res_emp = self.client.get(reverse('user_list'))
        self.assertEqual(res_emp.status_code, 403)

    def test_user_detail_idor_security(self):
        # Vice rector accessing employee in assigned department -> OK
        self.client.login(username='vr.acad', password='Password123!')
        res_ok = self.client.get(reverse('user_detail', kwargs={'pk': self.emp_it.pk}))
        self.assertEqual(res_ok.status_code, 200)

        # IDOR protection: Vice rector accessing employee in unassigned Finance department -> 403
        res_blocked = self.client.get(reverse('user_detail', kwargs={'pk': self.emp_fin.pk}))
        self.assertEqual(res_blocked.status_code, 403)

        # IDOR protection: Employee accessing other employee profile -> 403
        self.client.login(username='emp.it', password='Password123!')
        res_emp_other = self.client.get(reverse('user_detail', kwargs={'pk': self.emp_fin.pk}))
        self.assertEqual(res_emp_other.status_code, 403)

        # Employee accessing self -> OK
        res_self = self.client.get(reverse('user_detail', kwargs={'pk': self.emp_it.pk}))
        self.assertEqual(res_self.status_code, 200)

    def test_user_creation_rector_only(self):
        self.client.login(username='rector', password='Password123!')
        res = self.client.post(
            reverse('user_create'),
            {
                'username': 'newuser',
                'email': 'newuser@example.com',
                'first_name': 'New',
                'last_name': 'Person',
                'password': 'Password123!',
                'department': self.dept_it.pk,
                'roles': [self.emp_role.pk],
                'is_active': True,
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(User.objects.filter(username='newuser').exists())

        # Non-rector cannot create users
        self.client.login(username='head.it', password='Password123!')
        res_blocked = self.client.get(reverse('user_create'))
        self.assertEqual(res_blocked.status_code, 403)

    def test_user_toggle_active_rector_only_and_cannot_deactivate_self(self):
        self.client.login(username='rector', password='Password123!')

        # Rector deactivates an employee
        self.client.post(reverse('user_toggle_active', kwargs={'pk': self.emp_it.pk}))
        self.emp_it.refresh_from_db()
        self.assertFalse(self.emp_it.is_active)

        # Rector cannot deactivate own account
        self.client.post(reverse('user_toggle_active', kwargs={'pk': self.rector.pk}))
        self.rector.refresh_from_db()
        self.assertTrue(self.rector.is_active)
