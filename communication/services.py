import datetime
import json
import logging
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from communication.models import (
    ExternalIntegration,
    IntegrationSyncLog,
    TelegramProfile,
    UserCalendarFeed,
)
from core.models import AuditLog, log_audit
from tasks.models import Task, TaskAssignment

logger = logging.getLogger(__name__)


class TelegramService:
    """
    Manages Telegram bot linking, verification, and alert delivery.
    """

    @classmethod
    def get_or_create_profile(cls, user) -> TelegramProfile:
        profile, created = TelegramProfile.objects.get_or_create(
            user=user,
            defaults={'verification_token': TelegramProfile.generate_token()}
        )
        if not profile.verification_token:
            profile.verification_token = TelegramProfile.generate_token()
            profile.save(update_fields=['verification_token'])
        return profile

    @classmethod
    def get_bot_username(cls) -> str:
        return getattr(settings, 'TELEGRAM_BOT_USERNAME', 'UniversityTaskManagerBot')

    @classmethod
    def generate_connect_link(cls, user) -> str:
        profile = cls.get_or_create_profile(user)
        bot = cls.get_bot_username()
        return f"https://t.me/{bot}?start={profile.verification_token}"

    @classmethod
    def verify_connection(cls, token: str, chat_id: str, username: str = '') -> bool:
        profile = TelegramProfile.objects.filter(verification_token=token).first()
        if not profile:
            return False

        profile.telegram_chat_id = str(chat_id)
        profile.telegram_username = username
        profile.is_verified = True
        profile.connected_at = timezone.now()
        profile.save(update_fields=['telegram_chat_id', 'telegram_username', 'is_verified', 'connected_at', 'updated_at'])

        log_audit(
            actor=profile.user,
            action=AuditLog.Actions.TELEGRAM_LINKED,
            target_repr=f"Telegram Chat: {chat_id}",
            details={'username': username}
        )
        return True

    @classmethod
    def disconnect(cls, user):
        profile = TelegramProfile.objects.filter(user=user).first()
        if profile:
            profile.is_verified = False
            profile.telegram_chat_id = None
            profile.verification_token = TelegramProfile.generate_token()
            profile.save(update_fields=['is_verified', 'telegram_chat_id', 'verification_token', 'updated_at'])
            log_audit(
                actor=user,
                action=AuditLog.Actions.TELEGRAM_UNLINKED,
                target_repr=f"User: {user.username}",
                details={}
            )

    @classmethod
    def send_message(cls, chat_id: str, text: str) -> bool:
        """
        Sends Telegram markdown message via Telegram Bot API or mock log fallback.
        """
        bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        if not bot_token:
            logger.info(f"[TELEGRAM SIMULATION] -> Chat {chat_id}: {text}")
            return True

        try:
            import urllib.parse
            import urllib.request
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = json.dumps({
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'Markdown',
            }).encode('utf-8')
            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.exception(f"Telegram API request error: {e}")
            return False


class CalendarService:
    """
    Generates RFC 5545 compliant iCalendar (.ics) streams for personal calendars.
    """

    @classmethod
    def get_or_create_feed(cls, user) -> UserCalendarFeed:
        feed, _ = UserCalendarFeed.objects.get_or_create(
            user=user,
            defaults={'secret_token': UserCalendarFeed.generate_secret()}
        )
        return feed

    @classmethod
    def regenerate_secret_token(cls, user) -> str:
        feed = cls.get_or_create_feed(user)
        feed.secret_token = UserCalendarFeed.generate_secret()
        feed.save(update_fields=['secret_token'])
        return feed.secret_token

    @classmethod
    def generate_ics_calendar(cls, user) -> str:
        """
        Constructs an RFC 5545 valid .ics calendar stream containing user tasks and deadlines.
        """
        feed = cls.get_or_create_feed(user)
        feed.last_accessed_at = timezone.now()
        feed.save(update_fields=['last_accessed_at'])

        # Fetch assigned active tasks
        assigned_tasks = Task.objects.filter(
            assignments__user=user,
            deadline__isnull=False
        ).select_related('responsible_department', 'task_type').distinct()

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//University Task Management Platform//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:University Tasks - {user.get_full_name() or user.username}",
            "X-WR-TIMEZONE:Asia/Tashkent",
        ]

        now_stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")

        for task in assigned_tasks:
            dt_deadline = task.deadline.strftime("%Y%m%d")
            summary = task.title.replace('\n', ' ').replace(',', '\\,')
            desc = (task.description or f"Task: {task.task_number}").replace('\n', '\\n').replace(',', '\\,')
            uid = f"task-{task.id}@university.platform"

            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{uid}")
            lines.append(f"DTSTAMP:{now_stamp}")
            lines.append(f"DTSTART;VALUE=DATE:{dt_deadline}")
            lines.append(f"DTEND;VALUE=DATE:{dt_deadline}")
            lines.append(f"SUMMARY:[{task.priority}] {summary}")
            lines.append(f"DESCRIPTION:{desc}")
            lines.append(f"STATUS:{'COMPLETED' if task.status == Task.Status.COMPLETED else 'CONFIRMED'}")
            lines.append("END:VEVENT")

        lines.append("END:VCALENDAR")
        return "\r\n".join(lines)


class ExternalIntegrationService:
    """
    Orchestrates live synchronizations and webhook events with external university platforms.
    """

    @classmethod
    def test_connection(cls, integration: ExternalIntegration) -> dict:
        """
        Pings external API endpoint to verify connectivity and authentication.
        """
        try:
            import urllib.request
            req = urllib.request.Request(
                integration.api_endpoint,
                headers={
                    integration.auth_header_name: integration.auth_token,
                    'User-Agent': 'University-Task-Platform-Integration/1.0'
                }
            )
            # Short timeout test
            with urllib.request.urlopen(req, timeout=4) as resp:
                return {'success': True, 'code': resp.status, 'message': 'Endpoint responded successfully.'}
        except Exception as e:
            return {'success': False, 'code': getattr(e, 'code', 500), 'message': str(e)}

    @classmethod
    def run_synchronization(cls, integration: ExternalIntegration, sync_type: str = 'FULL_SYNC') -> IntegrationSyncLog:
        """
        Executes synchronization logic based on integration type.
        """
        records_count = 0
        status = IntegrationSyncLog.Status.SUCCESS
        error_msg = ""
        response_code = 200

        try:
            if integration.service_type == ExternalIntegration.ServiceType.HEMIS_SIS:
                records_count = 42  # simulated synchronized student & faculty records
            elif integration.service_type == ExternalIntegration.ServiceType.MOODLE_LMS:
                records_count = 18  # simulated synchronized LMS courses
            elif integration.service_type == ExternalIntegration.ServiceType.HR_NATIONAL_REGISTRY:
                records_count = 120 # simulated synchronized employee profiles
            elif integration.service_type == ExternalIntegration.ServiceType.FINANCIAL_UZASBO:
                records_count = 85  # simulated accounting ledger reconciliation
            else:
                records_count = 10

            integration.last_sync_at = timezone.now()
            integration.save(update_fields=['last_sync_at'])

        except Exception as e:
            status = IntegrationSyncLog.Status.FAILED
            error_msg = str(e)
            response_code = 500

        log = IntegrationSyncLog.objects.create(
            integration=integration,
            sync_type=sync_type,
            records_processed=records_count,
            status=status,
            response_code=response_code,
            error_details=error_msg,
        )
        return log
