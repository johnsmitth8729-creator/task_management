import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


class Department(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=255)
    code = models.CharField(_('code'), max_length=50, unique=True)
    description = models.TextField(_('description'), blank=True)
    is_active = models.BooleanField(_('active'), default=True)
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('department head'),
        on_delete=models.SET_NULL,
        related_name='headed_departments',
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = _('department')
        verbose_name_plural = _('departments')

    def __str__(self):
        return self.name

    @property
    def employee_count(self) -> int:
        return self.users.filter(is_active=True).count()

    @property
    def active_vice_rectors(self):
        return [
            resp.vice_rector
            for resp in self.vice_rector_responsibilities.filter(is_active=True).select_related('vice_rector')
        ]


class Position(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=255)
    code = models.CharField(_('code'), max_length=50, unique=True)
    description = models.TextField(_('description'), blank=True)
    department = models.ForeignKey(
        Department,
        verbose_name=_('department'),
        on_delete=models.SET_NULL,
        related_name='positions',
        blank=True,
        null=True,
        help_text=_('Leave blank if this position applies university-wide.'),
    )
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = _('position')
        verbose_name_plural = _('positions')

    def __str__(self):
        if self.department:
            return f"{self.name} ({self.department.code})"
        return self.name


class DepartmentResponsibility(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vice_rector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('vice rector'),
        on_delete=models.CASCADE,
        related_name='department_responsibilities',
    )
    department = models.ForeignKey(
        Department,
        verbose_name=_('department'),
        on_delete=models.CASCADE,
        related_name='vice_rector_responsibilities',
    )
    start_date = models.DateField(_('start date'), default=timezone.now)
    end_date = models.DateField(_('end date'), blank=True, null=True)
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['vice_rector', 'is_active']),
            models.Index(fields=['department', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['vice_rector', 'department'],
                condition=models.Q(is_active=True),
                name='unique_active_vice_rector_department_responsibility',
            )
        ]
        verbose_name = _('department responsibility')
        verbose_name_plural = _('department responsibilities')

    def __str__(self):
        return f"{self.vice_rector.display_name} -> {self.department.name}"

