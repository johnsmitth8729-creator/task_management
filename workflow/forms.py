from django import forms
from django.utils.translation import gettext_lazy as _


class TaskRejectionForm(forms.Form):
    reason = forms.CharField(
        label=_('Rejection Reason'),
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': _('Please provide a detailed reason for the rejection...'),
            'required': True,
        }),
        required=True,
    )


class TaskDeadlineExtensionForm(forms.Form):
    new_deadline = forms.DateField(
        label=_('New Deadline'),
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'required': True,
        }),
        required=True,
    )
    reason = forms.CharField(
        label=_('Extension Reason'),
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': _('Explain the necessity and justification for this deadline extension...'),
            'required': True,
        }),
        required=True,
    )


class TaskFirstApprovalForm(forms.Form):
    notes = forms.CharField(
        label=_('Approval Comments (Optional)'),
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': _('Add any optional notes or feedback for management review...'),
        }),
        required=False,
    )


class TaskFinalApprovalForm(forms.Form):
    notes = forms.CharField(
        label=_('Final Approval Notes (Optional)'),
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': _('Add any optional commendations or closure remarks...'),
        }),
        required=False,
    )
