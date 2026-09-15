from django import forms
from django.utils.translation import gettext_lazy as _

from automation.models import (
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)
from organization.models import Department
from tasks.models import Task, TaskTemplate, TaskType


class AutomationRuleForm(forms.ModelForm):
    class Meta:
        model = AutomationRule
        fields = [
            'name',
            'description',
            'trigger_event',
            'action_type',
            'priority_order',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'trigger_event': forms.Select(attrs={'class': 'form-select'}),
            'action_type': forms.Select(attrs={'class': 'form-select'}),
            'priority_order': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class RecurringTaskRuleForm(forms.ModelForm):
    class Meta:
        model = RecurringTaskRule
        fields = [
            'title',
            'description',
            'responsible_department',
            'priority',
            'recurrence_type',
            'day_of_week',
            'day_of_month',
            'time_of_day',
            'deadline_offset_days',
            'task_type',
            'template',
            'assignees',
            'is_active',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'responsible_department': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'recurrence_type': forms.Select(attrs={'class': 'form-select'}),
            'day_of_week': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0 (Mon) - 6 (Sun)'}),
            'day_of_month': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1 - 31'}),
            'time_of_day': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'deadline_offset_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'task_type': forms.Select(attrs={'class': 'form-select'}),
            'template': forms.Select(attrs={'class': 'form-select'}),
            'assignees': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class SLAPolicyForm(forms.ModelForm):
    class Meta:
        model = SLAPolicy
        fields = [
            'name',
            'priority',
            'first_response_hours',
            'resolution_hours',
            'warning_threshold_percent',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'first_response_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'resolution_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'warning_threshold_percent': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class EscalationPolicyForm(forms.ModelForm):
    class Meta:
        model = EscalationPolicy
        fields = [
            'name',
            'trigger_type',
            'hours_threshold',
            'escalate_to_role',
            'send_email',
            'send_telegram',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'trigger_type': forms.Select(attrs={'class': 'form-select'}),
            'hours_threshold': forms.NumberInput(attrs={'class': 'form-control'}),
            'escalate_to_role': forms.Select(attrs={'class': 'form-select'}),
            'send_email': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'send_telegram': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
