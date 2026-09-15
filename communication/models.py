import secrets
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class NotificationPreference(models.Model):
    """
    Per-user granular notification preferences by channel and notification category.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('user'),
        on_delete=models.CASCADE,
        related_name='notification_preference'
    )
    # Channel Master Toggles
    enable_in_app = models.BooleanField(_('enable in-app notifications'), default=True)
    enable_email = models.BooleanField(_('enable email notifications'), default=True)
    enable_telegram = models.BooleanField(_('enable telegram notifications'), default=True)
    enable_push = models.BooleanField(_('enable web push notifications'), default=True)

    # Category Granularity
    notify_task_assignments = models.BooleanField(_('task assignments'), default=True)
    notify_workflow_approvals = models.BooleanField(_('workflow & approval requests'), default=True)
    notify_deadline_reminders = models.BooleanField(_('deadline reminders & escalations'), default=True)
    notify_system_security = models.BooleanField(_('security & system updates'), default=True)
    notify_payroll_updates = models.BooleanField(_('personal payroll & compensation updates'), default=True)

    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('notification preference')
        verbose_name_plural = _('notification preferences')

    def __str__(self):
        return f"Preferences for {self.user.get_full_name() or self.user.username}"


class TelegramProfile(models.Model):
    """
    Telegram account connection for real-time university bot alerts.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('user'),
        on_delete=models.CASCADE,
        related_name='telegram_profile'
    )
    telegram_chat_id = models.CharField(_('telegram chat ID'), max_length=64, blank=True, null=True, db_index=True)
    telegram_username = models.CharField(_('telegram username'), max_length=100, blank=True)
    verification_token = models.CharField(_('verification token'), max_length=64, unique=True, db_index=True)
    is_verified = models.BooleanField(_('is connected and verified'), default=False)
    connected_at = models.DateTimeField(_('connected at'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('telegram profile')
        verbose_name_plural = _('telegram profiles')

    def __str__(self):
        status = "Verified" if self.is_verified else "Pending Verification"
        return f"Telegram ({self.telegram_username or self.telegram_chat_id or 'Unlinked'}) - {status}"

    @classmethod
    def generate_token(cls) -> str:
        return secrets.token_urlsafe(32)


class WebPushSubscription(models.Model):
    """
    Browser Web Push subscription credentials for desktop & mobile push.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('user'),
        on_delete=models.CASCADE,
        related_name='web_push_subscriptions'
    )
    endpoint = models.TextField(_('push endpoint'), unique=True)
    p256dh_key = models.CharField(_('P256DH key'), max_length=255)
    auth_key = models.CharField(_('auth key'), max_length=255)
    user_agent = models.CharField(_('client user agent'), max_length=255, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('web push subscription')
        verbose_name_plural = _('web push subscriptions')
        ordering = ['-created_at']

    def __str__(self):
        return f"Push Sub for {self.user.username} ({self.created_at:%Y-%m-%d})"


class UserCalendarFeed(models.Model):
    """
    Private secure token for RFC 5545 iCalendar calendar synchronization.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('user'),
        on_delete=models.CASCADE,
        related_name='calendar_feed'
    )
    secret_token = models.CharField(_('calendar feed secret token'), max_length=64, unique=True, db_index=True)
    is_active = models.BooleanField(_('is active'), default=True)
    include_deadlines = models.BooleanField(_('include task deadlines'), default=True)
    include_approvals = models.BooleanField(_('include pending approval milestones'), default=True)
    last_accessed_at = models.DateTimeField(_('last synced by external calendar'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        verbose_name = _('calendar feed')
        verbose_name_plural = _('calendar feeds')

    def __str__(self):
        return f"Calendar Feed ({self.user.username})"

    @classmethod
    def generate_secret(cls) -> str:
        return secrets.token_hex(24)


class ExternalIntegration(models.Model):
    """
    Configuration and credentials for external university and governmental systems.
    """
    class ServiceType(models.TextChoices):
        HEMIS_SIS = 'HEMIS_SIS', _('HEMIS Higher Education Management System')
        MOODLE_LMS = 'MOODLE_LMS', _('Moodle LMS Platform')
        HR_NATIONAL_REGISTRY = 'HR_REGISTRY', _('National Ministry HR Registry')
        FINANCIAL_UZASBO = 'UZASBO_FINANCE', _('UzASBO / University Treasury')
        CUSTOM_WEBHOOK = 'CUSTOM_WEBHOOK', _('Custom Enterprise Webhook')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('integration name'), max_length=150)
    service_type = models.CharField(_('service type'), max_length=40, choices=ServiceType.choices)
    api_endpoint = models.URLField(_('API base endpoint URL'), max_length=500)
    auth_header_name = models.CharField(_('auth header name'), max_length=100, default='Authorization')
    auth_token = models.CharField(_('API authentication token / secret'), max_length=500, blank=True)
    is_active = models.BooleanField(_('is active'), default=True)
    config_payload = models.JSONField(
        _('custom configuration'),
        default=dict,
        blank=True,
        help_text=_('JSON parameters, webhook secrets, retry policies, or sync filters.')
    )
    last_sync_at = models.DateTimeField(_('last synchronized at'), null=True, blank=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('external integration')
        verbose_name_plural = _('external integrations')
        ordering = ['name']

    def __str__(self):
        status = "Active" if self.is_active else "Disabled"
        return f"{self.name} ({self.get_service_type_display()}) - {status}"


class IntegrationSyncLog(models.Model):
    """
    Audit log of synchronization runs between the platform and external systems.
    """
    class Status(models.TextChoices):
        SUCCESS = 'SUCCESS', _('Success')
        FAILED = 'FAILED', _('Failed')
        PARTIAL = 'PARTIAL', _('Partial Success')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration = models.ForeignKey(
        ExternalIntegration,
        verbose_name=_('integration'),
        on_delete=models.CASCADE,
        related_name='sync_logs'
    )
    sync_type = models.CharField(_('sync operation type'), max_length=80, default='SYNC_ROUTINE')
    records_processed = models.PositiveIntegerField(_('records processed count'), default=0)
    status = models.CharField(_('execution status'), max_length=20, choices=Status.choices)
    response_code = models.IntegerField(_('HTTP response status code'), null=True, blank=True)
    error_details = models.TextField(_('error message or trace details'), blank=True)
    created_at = models.DateTimeField(_('executed at'), auto_now_add=True)

    class Meta:
        verbose_name = _('integration sync log')
        verbose_name_plural = _('integration sync logs')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.integration.name} Sync ({self.get_status_display()}) at {self.created_at:%Y-%m-%d %H:%M}"
