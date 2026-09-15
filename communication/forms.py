from django import forms
from django.utils.translation import gettext_lazy as _

from communication.models import (
    ExternalIntegration,
    NotificationPreference,
    TelegramProfile,
)


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = [
            'enable_in_app',
            'enable_email',
            'enable_telegram',
            'enable_push',
            'notify_task_assignments',
            'notify_workflow_approvals',
            'notify_deadline_reminders',
            'notify_system_security',
            'notify_payroll_updates',
        ]
        widgets = {
            'enable_in_app': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_email': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_telegram': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_push': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_task_assignments': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_workflow_approvals': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_deadline_reminders': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_system_security': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notify_payroll_updates': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ExternalIntegrationForm(forms.ModelForm):
    class Meta:
        model = ExternalIntegration
        fields = [
            'name',
            'service_type',
            'api_endpoint',
            'auth_header_name',
            'auth_token',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. University HEMIS SIS')}),
            'service_type': forms.Select(attrs={'class': 'form-select'}),
            'api_endpoint': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://api.hemis.edu.uz/v1'}),
            'auth_header_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Authorization'}),
            'auth_token': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': _('Bearer token or API Secret')}, render_value=True),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
