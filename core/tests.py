from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class CoreViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='coreuser',
            email='core@example.com',
            password='CorePassword123!',
            first_name='Core',
            last_name='User',
        )

    def test_anonymous_user_redirected_from_dashboard(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_authenticated_user_can_access_dashboard(self):
        self.client.login(username='coreuser', password='CorePassword123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome, Core User')
        self.assertContains(response, 'Phase 1 foundation dashboard')

    def test_home_redirect_for_anonymous_user(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('login'))

    def test_home_redirect_for_authenticated_user(self):
        self.client.login(username='coreuser', password='CorePassword123!')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))


class AdminRegistrationTests(TestCase):
    def test_admin_models_registered(self):
        from django.contrib import admin
        from accounts.models import Role, User
        from organization.models import Department, Position

        self.assertIn(Role, admin.site._registry)
        self.assertIn(User, admin.site._registry)
        self.assertIn(Department, admin.site._registry)
        self.assertIn(Position, admin.site._registry)


class ErrorPagesTests(TestCase):
    def test_404_handler(self):
        response = self.client.get('/non-existent-url-path-404/')
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')


class LanguageConfigTests(TestCase):
    def test_configured_languages(self):
        supported_codes = [code for code, name in settings.LANGUAGES]
        self.assertIn('uz', supported_codes)
        self.assertIn('en', supported_codes)
        self.assertIn('ru', supported_codes)
        self.assertEqual(len(supported_codes), 3)

    def test_language_switch_endpoint(self):
        response = self.client.post(
            reverse('set_language'),
            {'language': 'uz', 'next': reverse('login')},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, 'uz')
