import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


class EmployeeGrade(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('name'), max_length=150)
    code = models.CharField(_('code'), max_length=50, unique=True)
    description = models.TextField(_('description'), blank=True)
    rank = models.IntegerField(_('rank / level order'), default=1, help_text=_('Lower number means entry level, higher number means executive/senior rank.'))
    is_active = models.BooleanField(_('active'), default=True)

    class Meta:
        ordering = ['rank', 'code']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['rank']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = _('employee grade')
        verbose_name_plural = _('employee grades')

    def __str__(self):
        return f"{self.code} — {self.name}"


class HRPermissionConfig(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('authorized user'),
        on_delete=models.CASCADE,
        related_name='hr_authority',
    )
    # Employee Management
    can_view_employees = models.BooleanField(_('can view employees'), default=True)
    can_create_employees = models.BooleanField(_('can create employees'), default=False)
    can_edit_employees = models.BooleanField(_('can edit employees'), default=True)
    can_deactivate_employees = models.BooleanField(_('can deactivate employees'), default=False)
    can_assign_department = models.BooleanField(_('can assign department'), default=True)
    can_assign_position = models.BooleanField(_('can assign position'), default=True)
    can_assign_grade = models.BooleanField(_('can assign grade'), default=True)
    can_assign_supervisor = models.BooleanField(_('can assign supervisor'), default=True)

    # Organizational Hierarchy
    can_manage_departments = models.BooleanField(_('can manage departments'), default=False)
    can_assign_department_head = models.BooleanField(_('can assign department head'), default=False)
    can_assign_vice_rector_responsibility = models.BooleanField(_('can assign vice rector responsibility'), default=False)

    # KPI Management
    can_view_kpi = models.BooleanField(_('can view KPI'), default=True)
    can_manage_kpi = models.BooleanField(_('can manage KPI definitions & assignments'), default=False)
    can_approve_kpi = models.BooleanField(_('can approve KPI results'), default=False)

    # Phase 8 — Payroll Management
    can_view_payroll = models.BooleanField(_('can view payroll'), default=False)
    can_manage_salary = models.BooleanField(_('can manage employee salaries'), default=False)
    can_create_adjustment = models.BooleanField(_('can create payroll adjustments'), default=False)
    can_manage_payroll = models.BooleanField(_('can manage payroll periods & calculation'), default=False)
    can_approve_payroll = models.BooleanField(_('can approve payroll records'), default=False)
    can_mark_paid = models.BooleanField(_('can mark payroll as paid'), default=False)
    can_view_payroll_reports = models.BooleanField(_('can view payroll reports'), default=False)

    class Meta:
        verbose_name = _('HR authority configuration')
        verbose_name_plural = _('HR authority configurations')

    def __str__(self):
        return f"HR Authority ({self.user.display_name})"
