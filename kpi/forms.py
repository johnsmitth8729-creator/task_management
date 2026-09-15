from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from hr.models import EmployeeGrade
from kpi.models import (
    KPIAssignment,
    KPICategory,
    KPICorrectionRequest,
    KPIDefinition,
    KPIPeriod,
    KPIResult,
)
from organization.models import Department, Position


class KPICategoryForm(forms.ModelForm):
    class Meta:
        model = KPICategory
        fields = ['name', 'code', 'description', 'order', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class KPIPeriodForm(forms.ModelForm):
    class Meta:
        model = KPIPeriod
        fields = ['name', 'code', 'period_type', 'start_date', 'end_date', 'status', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 2026 Q1'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 2026-Q1'}),
            'period_type': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class KPIDefinitionForm(forms.ModelForm):
    class Meta:
        model = KPIDefinition
        fields = [
            'name',
            'code',
            'category',
            'description',
            'measurement_type',
            'source_type',
            'direction',
            'no_data_policy',
            'target_value',
            'configured_weight',
            'min_value',
            'max_value',
            'applicable_department',
            'applicable_position',
            'applicable_grade',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'measurement_type': forms.Select(attrs={'class': 'form-select'}),
            'source_type': forms.Select(attrs={'class': 'form-select'}),
            'direction': forms.Select(attrs={'class': 'form-select'}),
            'no_data_policy': forms.Select(attrs={'class': 'form-select'}),
            'target_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'configured_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'min_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'max_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'applicable_department': forms.Select(attrs={'class': 'form-select'}),
            'applicable_position': forms.Select(attrs={'class': 'form-select'}),
            'applicable_grade': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class KPIAssignmentForm(forms.ModelForm):
    class Meta:
        model = KPIAssignment
        fields = ['kpi', 'user', 'period', 'target_value', 'configured_weight', 'source_type', 'is_active']
        widgets = {
            'kpi': forms.Select(attrs={'class': 'form-select'}),
            'user': forms.Select(attrs={'class': 'form-select'}),
            'period': forms.Select(attrs={'class': 'form-select'}),
            'target_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'configured_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'source_type': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class KPIResultEvaluationForm(forms.ModelForm):
    class Meta:
        model = KPIResult
        fields = ['actual_value', 'notes']
        widgets = {
            'actual_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Evaluator remarks or justification...')}),
        }


class KPICorrectionRequestForm(forms.ModelForm):
    class Meta:
        model = KPICorrectionRequest
        fields = ['requested_actual_value', 'reason', 'evidence']
        widgets = {
            'requested_actual_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Reason and justification for correction request...')}),
            'evidence': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Supporting documentation links, task references, or evidence...')}),
        }
