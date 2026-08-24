import uuid
from django.contrib.auth import authenticate, get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from organization.models import Department, Position

User = get_user_model()


class UserModelTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name='Information Technology',
            code='IT',
            description='IT Department',
        )
        self.position = Position.objects.create(
            name='Developer',
            code='DEV',
            description='Software Developer',
        )
        self.role = Role.objects.create(
            code=Role.Codes.EMPLOYEE,
            name='Employee / User',
        )

    def test_custom_user_creation(self):
        user = User.objects.create_user(
            username='johndoe',
            email='john@example.com',
            password='SecretPassword123!',
            first_name='John',
            last_name='Doe',
            department=self.department,
            position=self.position,
        )
        user.roles.add(self.role)

        self.assertIsInstance(user.id, uuid.UUID)
        self.assertEqual(user.username, 'johndoe')
        self.assertEqual(user.email, 'john@example.com')
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
        self.assertEqual(user.display_name, 'John Doe')
        self.assertEqual(user.department, self.department)
        self.assertEqual(user.position, self.position)
        self.assertTrue(user.has_role(Role.Codes.EMPLOYEE))
        self.assertFalse(user.has_role(Role.Codes.RECTOR))

    def test_password_is_hashed(self):
        user = User.objects.create_user(
            username='janedoe',
            email='jane@example.com',
            password='MySecurePassword456!',
        )
        self.assertNotEqual(user.password, 'MySecurePassword456!')
        self.assertTrue(user.check_password('MySecurePassword456!'))
        self.assertFalse(user.check_password('WrongPassword!'))

    def test_inactive_user_cannot_authenticate(self):
        user = User.objects.create_user(
            username='inactiveuser',
            email='inactive@example.com',
            password='Password123!',
            is_active=False,
        )
        authenticated = authenticate(username='inactiveuser', password='Password123!')
        self.assertIsNone(authenticated)

    def test_user_display_name_fallback_to_username(self):
        user = User.objects.create_user(
            username='fallbackuser',
            email='fallback@example.com',
            password='Password123!',
        )
        self.assertEqual(user.display_name, 'fallbackuser')

    def test_role_str_representation(self):
        self.assertEqual(str(self.role), 'Employee / User')


class AuthenticationViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='TestPassword123!',
            first_name='Test',
            last_name='User',
        )

    def test_login_page_renders_successfully(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TASK MANAGEMENT')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'name="remember_me"')

    def test_successful_login(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': 'testuser',
                'password': 'TestPassword123!',
            },
            follow=True,
        )
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].username, 'testuser')
        self.assertRedirects(response, reverse('dashboard'))

    def test_wrong_password_fails_login(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': 'testuser',
                'password': 'IncorrectPassword!',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)
        self.assertTrue(response.context['form'].errors)

    def test_inactive_user_login_fails(self):
        self.user.is_active = False
        self.user.save()

        response = self.client.post(
            reverse('login'),
            {
                'username': 'testuser',
                'password': 'TestPassword123!',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)

    def test_logout_works(self):
        self.client.login(username='testuser', password='TestPassword123!')
        response = self.client.post(reverse('logout'), follow=True)
        self.assertFalse(response.context['user'].is_authenticated)
        self.assertRedirects(response, reverse('login'))

    def test_remember_me_session_expiry(self):
        # Without remember me, session expires at browser close (expiry set to 0)
        client_no_remember = Client()
        client_no_remember.post(
            reverse('login'),
            {
                'username': 'testuser',
                'password': 'TestPassword123!',
                'remember_me': False,
            },
        )
        self.assertTrue(client_no_remember.session.get_expire_at_browser_close())

        # With remember me, session uses default expiry and does not expire at browser close
        client_remember = Client()
        client_remember.post(
            reverse('login'),
            {
                'username': 'testuser',
                'password': 'TestPassword123!',
                'remember_me': True,
            },
        )
        self.assertFalse(client_remember.session.get_expire_at_browser_close())
