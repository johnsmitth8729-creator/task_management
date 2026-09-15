from django import forms
from django.utils.translation import gettext_lazy as _

from files.models import TaskFile, TaskFolder, TaskReport


class TaskFileUploadForm(forms.ModelForm):
    class Meta:
        model = TaskFile
        fields = ['file', 'folder', 'category', 'description']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-control', 'required': 'required'}),
            'folder': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': _('Optional description or notes about this file...')}),
        }

    def __init__(self, *args, task=None, **kwargs):
        super().__init__(*args, **kwargs)
        if task:
            self.fields['folder'].queryset = TaskFolder.objects.filter(task=task, is_active=True).order_by('name')
            self.fields['folder'].empty_label = _('Root / No Folder')
        else:
            self.fields['folder'].queryset = TaskFolder.objects.none()


class TaskFolderForm(forms.ModelForm):
    class Meta:
        model = TaskFolder
        fields = ['name', 'parent_folder']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. Development, Reports, Screenshots'), 'required': 'required'}),
            'parent_folder': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, task=None, **kwargs):
        super().__init__(*args, **kwargs)
        if task:
            self.fields['parent_folder'].queryset = TaskFolder.objects.filter(task=task, is_active=True).order_by('name')
            self.fields['parent_folder'].empty_label = _('Root Level (No Parent)')
        else:
            self.fields['parent_folder'].queryset = TaskFolder.objects.none()


class TaskReportForm(forms.ModelForm):
    class Meta:
        model = TaskReport
        fields = [
            'title',
            'reporting_period',
            'summary',
            'completed_work',
            'results',
            'problems',
            'recommendations',
            'conclusion',
            'status',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. Final Work Report & Deliverables Summary'), 'required': 'required'}),
            'reporting_period': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. Q3 2026 / Final Milestone')}),
            'summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('High-level executive summary of the report...'), 'required': 'required'}),
            'completed_work': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': _('Detailed breakdown of completed activities and milestones...'), 'required': 'required'}),
            'results': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Key deliverables, metrics, and measurable outcomes...'), 'required': 'required'}),
            'problems': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': _('Any obstacles, risks, or technical challenges encountered...')}),
            'recommendations': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': _('Proposed future actions or follow-up recommendations...')}),
            'conclusion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': _('Closing remarks or summary evaluation...')}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
