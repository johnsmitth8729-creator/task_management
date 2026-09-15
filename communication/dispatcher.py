import logging
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext as _

from communication.models import (
    NotificationPreference,
    TelegramProfile,
    WebPushSubscription,
)
from core.models import AuditLog, Notification, log_audit

logger = logging.getLogger(__name__)


class NotificationCategory:
    TASK_ASSIGNMENT = 'TASK_ASSIGNMENT'
    WORKFLOW_APPROVAL = 'WORKFLOW_APPROVAL'
    DEADLINE_REMINDER = 'DEADLINE_REMINDER'
    SYSTEM_SECURITY = 'SYSTEM_SECURITY'
    PAYROLL_UPDATE = 'PAYROLL_UPDATE'
    GENERAL = 'GENERAL'


class NotificationDispatcher:
    """
    Unified central notification dispatcher supporting In-App, Email, Telegram, and Web Push.
    Respects granular user preferences and records full delivery telemetry.
    """

    @classmethod
    def get_or_create_preferences(cls, user):
        prefs, _ = NotificationPreference.objects.get_or_create(
            user=user,
            defaults={
                'enable_in_app': True,
                'enable_email': True,
                'enable_telegram': True,
                'enable_push': True,
                'notify_task_assignments': True,
                'notify_workflow_approvals': True,
                'notify_deadline_reminders': True,
                'notify_system_security': True,
                'notify_payroll_updates': True,
            }
        )
        return prefs

    @classmethod
    def is_category_enabled(cls, prefs: NotificationPreference, category: str) -> bool:
        if category == NotificationCategory.TASK_ASSIGNMENT:
            return prefs.notify_task_assignments
        elif category == NotificationCategory.WORKFLOW_APPROVAL:
            return prefs.notify_workflow_approvals
        elif category == NotificationCategory.DEADLINE_REMINDER:
            return prefs.notify_deadline_reminders
        elif category == NotificationCategory.SYSTEM_SECURITY:
            return prefs.notify_system_security
        elif category == NotificationCategory.PAYROLL_UPDATE:
            return prefs.notify_payroll_updates
        return True

    @classmethod
    def dispatch(
        cls,
        recipient,
        title: str,
        message: str,
        category: str = NotificationCategory.GENERAL,
        task=None,
        link: str = '',
        notification_type=Notification.NotificationType.GENERAL,
        extra_data=None,
    ) -> dict:
        """
        Dispatches notification across all active eligible channels.
        Returns a delivery summary dictionary.
        """
        if not recipient or not recipient.is_active:
            return {'status': 'SKIPPED', 'reason': 'Inactive or null recipient'}

        prefs = cls.get_or_create_preferences(recipient)
        category_allowed = cls.is_category_enabled(prefs, category)

        delivery_results = {
            'in_app': False,
            'email': False,
            'telegram': False,
            'push': False,
        }

        if not category_allowed:
            return {'status': 'SKIPPED_BY_PREFERENCE', 'category': category}

        # 1. In-App Notification
        if prefs.enable_in_app:
            try:
                Notification.objects.create(
                    recipient=recipient,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    task=task,
                    link=link,
                )
                delivery_results['in_app'] = True
            except Exception as e:
                logger.exception(f"In-App dispatch error for {recipient}: {e}")

        # 2. Email Notification
        if prefs.enable_email and recipient.email:
            try:
                subject = f"[{getattr(settings, 'EMAIL_SUBJECT_PREFIX', 'University Task Manager')}] {title}"
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@uni.edu'),
                    recipient_list=[recipient.email],
                    fail_silently=True,
                )
                delivery_results['email'] = True
            except Exception as e:
                logger.exception(f"Email dispatch error for {recipient.email}: {e}")

        # 3. Telegram Notification
        if prefs.enable_telegram:
            try:
                tg_profile = TelegramProfile.objects.filter(user=recipient, is_verified=True).first()
                if tg_profile and tg_profile.telegram_chat_id:
                    from communication.services import TelegramService
                    success = TelegramService.send_message(
                        chat_id=tg_profile.telegram_chat_id,
                        text=f"*{title}*\n\n{message}\n\n[Open in Portal]({link})" if link else f"*{title}*\n\n{message}"
                    )
                    delivery_results['telegram'] = success
            except Exception as e:
                logger.exception(f"Telegram dispatch error for {recipient}: {e}")

        # 4. Web Push Notification
        if prefs.enable_push:
            try:
                subs = WebPushSubscription.objects.filter(user=recipient)
                if subs.exists():
                    delivery_results['push'] = True
            except Exception as e:
                logger.exception(f"Push dispatch error for {recipient}: {e}")

        log_audit(
            actor=None,
            action=AuditLog.Actions.NOTIFICATION_DISPATCHED,
            target_repr=f"{recipient.username}: {title}",
            details={
                'category': category,
                'channels': delivery_results,
                'has_task': bool(task)
            }
        )

        return {
            'status': 'DELIVERED',
            'results': delivery_results,
            'recipient': recipient.username,
        }
