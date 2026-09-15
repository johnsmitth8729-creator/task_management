import datetime
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from communication.dispatcher import (
    NotificationCategory,
    NotificationDispatcher,
)
from communication.models import (
    ExternalIntegration,
    IntegrationSyncLog,
    NotificationPreference,
    TelegramProfile,
    UserCalendarFeed,
)
from communication.services import (
    CalendarService,
    ExternalIntegrationService,
    TelegramService,
)
from core.models import Notification
from organization.models import Department, Position
from tasks.models import Task, TaskAssignment, TaskType

User = get_user_model()


class CommunicationDispatcherTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='Academic Affairs', code='ACAD_DEPT')
        self.superadmin = User.objects.create_superuser(
            username='comm_admin',
            email='admin@uni.edu',
            password='Password123!',
        )
        self.employee = User.objects.create_user(
            username='comm_emp',
            email='employee@uni.edu',
            password='Password123!',
            department=self.dept,
        )
        self.task_type = TaskType.objects.create(name='Academic', code='ACAD')
        self.task = Task.objects.create(
            title='Curriculum Review 2026',
            priority=Task.Priority.HIGH,
            task_type=self.task_type,
            creator=self.superadmin,
            responsible_department=self.dept,
            deadline=timezone.now().date() + datetime.timedelta(days=5),
        )

    def test_notification_dispatcher_in_app_and_email(self):
        res = NotificationDispatcher.dispatch(
            recipient=self.employee,
            title='New Assignment Ready',
            message='Please review curriculum draft.',
            category=NotificationCategory.TASK_ASSIGNMENT,
            task=self.task,
        )
        self.assertEqual(res['status'], 'DELIVERED')
        self.assertTrue(res['results']['in_app'])
        self.assertTrue(res['results']['email'])
        self.assertTrue(Notification.objects.filter(recipient=self.employee, task=self.task).exists())

    def test_category_preference_filtering(self):
        prefs = NotificationDispatcher.get_or_create_preferences(self.employee)
        prefs.notify_deadline_reminders = False
        prefs.save()

        res = NotificationDispatcher.dispatch(
            recipient=self.employee,
            title='Deadline Approaching',
            message='Task is due tomorrow.',
            category=NotificationCategory.DEADLINE_REMINDER,
            task=self.task,
        )
        self.assertEqual(res['status'], 'SKIPPED_BY_PREFERENCE')
        self.assertFalse(Notification.objects.filter(recipient=self.employee, title='Deadline Approaching').exists())

    def test_telegram_linking_and_delivery(self):
        profile = TelegramService.get_or_create_profile(self.employee)
        self.assertFalse(profile.is_verified)
        self.assertTrue(bool(profile.verification_token))

        # Verify linking
        verified = TelegramService.verify_connection(
            token=profile.verification_token,
            chat_id='987654321',
            username='emp_telegram'
        )
        self.assertTrue(verified)
        profile.refresh_from_db()
        self.assertTrue(profile.is_verified)
        self.assertEqual(profile.telegram_chat_id, '987654321')

        # Test Telegram message sending
        sent = TelegramService.send_message(chat_id=profile.telegram_chat_id, text='*Test Alert*')
        self.assertTrue(sent)

        # Test disconnect
        TelegramService.disconnect(self.employee)
        profile.refresh_from_db()
        self.assertFalse(profile.is_verified)
        self.assertIsNone(profile.telegram_chat_id)

    def test_calendar_service_ics_generation(self):
        TaskAssignment.objects.create(
            task=self.task,
            user=self.employee,
            assigned_by=self.superadmin,
        )
        ics_text = CalendarService.generate_ics_calendar(self.employee)
        self.assertIn('BEGIN:VCALENDAR', ics_text)
        self.assertIn('END:VCALENDAR', ics_text)
        self.assertIn('BEGIN:VEVENT', ics_text)
        self.assertIn('Curriculum Review 2026', ics_text)

    def test_external_integration_service(self):
        integration = ExternalIntegration.objects.create(
            name='HEMIS SIS Connector',
            service_type=ExternalIntegration.ServiceType.HEMIS_SIS,
            api_endpoint='https://api.hemis.edu.uz/v1/sync',
            auth_token='secret_test_token',
            is_active=True,
        )
        log = ExternalIntegrationService.run_synchronization(integration)
        self.assertEqual(log.status, IntegrationSyncLog.Status.SUCCESS)
        self.assertGreater(log.records_processed, 0)
        integration.refresh_from_db()
        self.assertIsNotNone(integration.last_sync_at)


class CommunicationViewsTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            username='admin_views',
            email='admin_views@uni.edu',
            password='Password123!',
        )
        self.employee = User.objects.create_user(
            username='emp_views',
            email='emp_views@uni.edu',
            password='Password123!',
        )
        self.notif = Notification.objects.create(
            recipient=self.employee,
            title='Welcome Notification',
            message='System initialized.',
        )

    def test_notification_center_and_mark_read(self):
        self.client.force_login(self.employee)
        res = self.client.get(reverse('communication:notification_center'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Welcome Notification')

        # Mark single as read
        res_post = self.client.post(reverse('communication:notification_mark_read', kwargs={'pk': self.notif.id}))
        self.assertEqual(res_post.status_code, 302)
        self.notif.refresh_from_db()
        self.assertTrue(self.notif.is_read)

    def test_preferences_view(self):
        self.client.force_login(self.employee)
        res = self.client.get(reverse('communication:preferences'))
        self.assertEqual(res.status_code, 200)

        res_post = self.client.post(reverse('communication:preferences'), {
            'enable_in_app': True,
            'enable_email': False,
            'enable_telegram': True,
            'enable_push': False,
            'notify_task_assignments': True,
            'notify_workflow_approvals': True,
            'notify_deadline_reminders': False,
            'notify_system_security': True,
            'notify_payroll_updates': True,
        })
        self.assertEqual(res_post.status_code, 302)
        prefs = NotificationPreference.objects.get(user=self.employee)
        self.assertFalse(prefs.enable_email)
        self.assertFalse(prefs.notify_deadline_reminders)

    def test_calendar_feed_endpoint(self):
        feed = CalendarService.get_or_create_feed(self.employee)
        res = self.client.get(reverse('communication:calendar_feed', kwargs={'token': feed.secret_token}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'text/calendar; charset=utf-8')
        self.assertIn(b'BEGIN:VCALENDAR', res.content)

    def test_integration_hub_rbac(self):
        # Superadmin allowed
        self.client.force_login(self.superadmin)
        res = self.client.get(reverse('communication:integration_hub'))
        self.assertEqual(res.status_code, 200)

        # Standard employee forbidden / 403
        self.client.force_login(self.employee)
        res = self.client.get(reverse('communication:integration_hub'))
        self.assertEqual(res.status_code, 403)
