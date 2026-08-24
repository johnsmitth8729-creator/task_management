import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditLog(models.Model):
    class Actions(models.TextChoices):
        USER_CREATED = 'USER_CREATED', _('User Created')
        USER_UPDATED = 'USER_UPDATED', _('User Updated')
        USER_ACTIVATED = 'USER_ACTIVATED', _('User Activated')
        USER_DEACTIVATED = 'USER_DEACTIVATED', _('User Deactivated')
        ROLE_CHANGED = 'ROLE_CHANGED', _('Role Changed')
        DEPARTMENT_CREATED = 'DEPARTMENT_CREATED', _('Department Created')
        DEPARTMENT_UPDATED = 'DEPARTMENT_UPDATED', _('Department Updated')
        DEPARTMENT_HEAD_ASSIGNED = 'DEPARTMENT_HEAD_ASSIGNED', _('Department Head Assigned')
        DEPARTMENT_HEAD_CHANGED = 'DEPARTMENT_HEAD_CHANGED', _('Department Head Changed')
        VICE_RECTOR_RESPONSIBILITY_ASSIGNED = (
            'VICE_RECTOR_RESPONSIBILITY_ASSIGNED',
            _('Vice Rector Responsibility Assigned'),
        )
        VICE_RECTOR_RESPONSIBILITY_REMOVED = (
            'VICE_RECTOR_RESPONSIBILITY_REMOVED',
            _('Vice Rector Responsibility Removed'),
        )
        POSITION_CREATED = 'POSITION_CREATED', _('Position Created')
        POSITION_UPDATED = 'POSITION_UPDATED', _('Position Updated')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('actor'),
        on_delete=models.SET_NULL,
        related_name='audit_logs',
        null=True,
        blank=True,
    )
    action = models.CharField(_('action'), max_length=64, choices=Actions.choices)
    target_repr = models.CharField(_('target'), max_length=255, blank=True)
    details = models.JSONField(_('details'), default=dict, blank=True)
    ip_address = models.GenericIPAddressField(_('IP address'), null=True, blank=True)
    created_at = models.DateTimeField(_('timestamp'), auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action']),
            models.Index(fields=['created_at']),
            models.Index(fields=['actor', 'created_at']),
        ]
        verbose_name = _('audit log')
        verbose_name_plural = _('audit logs')

    def __str__(self):
        actor_name = self.actor.display_name if self.actor else _('System')
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_name} -> {self.get_action_display()}: {self.target_repr}"


def log_audit(actor, action: str, target_repr: str = '', details: dict | None = None, request=None) -> AuditLog:
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')

    return AuditLog.objects.create(
        actor=actor if (actor and actor.is_authenticated) else None,
        action=action,
        target_repr=str(target_repr)[:255],
        details=details or {},
        ip_address=ip_address,
    )
