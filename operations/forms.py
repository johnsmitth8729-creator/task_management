from django import forms
from django.utils.translation import gettext_lazy as _

from operations.models import (
    DocumentVersion,
    RequestApprovalStep,
    RequestType,
    UniversityDocument,
    UniversityRequest,
)


class UniversityRequestForm(forms.ModelForm):
    class Meta:
        model = UniversityRequest
        fields = ['request_type', 'subject', 'is_urgent']
        widgets = {
            'request_type': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Brief subject of your application')}),
            'is_urgent': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class RequestApprovalDecisionForm(forms.Form):
    DECISION_CHOICES = (
        ('APPROVED', _('Approve Request')),
        ('REJECTED', _('Reject Request')),
    )
    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label=_('Decision')
    )
    comments = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Add rationale, feedback, or justification...')}),
        label=_('Comments / Justification')
    )


class UniversityDocumentForm(forms.ModelForm):
    class Meta:
        model = UniversityDocument
        fields = [
            'doc_number',
            'title',
            'document_type',
            'description',
            'file',
            'effective_date',
            'expiry_date',
            'status',
        ]
        widgets = {
            'doc_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. 104-B/2026')}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Official Title')}),
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'effective_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }


class DocumentVersionForm(forms.ModelForm):
    class Meta:
        model = DocumentVersion
        fields = ['file', 'changelog']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'changelog': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('What changed in this version?')}),
        }
