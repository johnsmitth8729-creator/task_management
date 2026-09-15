from decimal import Decimal
from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from organization.models import Department
from payroll.models import (
    CompensationComponent,
    KPIPayrollRule,
    PayrollAdjustment,
    PayrollPeriod,
    PayrollTaxRule,
    SalaryBand,
    SalaryProfile,
)


class SalaryProfileForm(forms.ModelForm):
    class Meta:
        model = SalaryProfile
        fields = [
            'base_salary',
            'currency',
            'salary_type',
            'effective_from',
            'effective_to',
            'notes',
        ]
        widgets = {
            'base_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '1'}),
            'currency': forms.TextInput(attrs={'class': 'form-control'}),
            'salary_type': forms.Select(attrs={'class': 'form-select'}),
            'effective_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'effective_to': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Reason for adjustment / promotion notes...')}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get('effective_from'):
            self.initial['effective_from'] = timezone.now().date()


class PayrollPeriodForm(forms.ModelForm):
    class Meta:
        model = PayrollPeriod
        fields = [
            'name',
            'code',
            'period_type',
            'start_date',
            'end_date',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. October 2026')}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. 2026-10')}),
            'period_type': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class CompensationComponentForm(forms.ModelForm):
    class Meta:
        model = CompensationComponent
        fields = [
            'name',
            'code',
            'component_type',
            'calculation_type',
            'default_value',
            'is_taxable',
            'is_active',
            'description',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'component_type': forms.Select(attrs={'class': 'form-select'}),
            'calculation_type': forms.Select(attrs={'class': 'form-select'}),
            'default_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_taxable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class PayrollAdjustmentForm(forms.ModelForm):
    class Meta:
        model = PayrollAdjustment
        fields = [
            'employee',
            'period',
            'type',
            'amount',
            'reason',
        ]
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'period': forms.Select(attrs={'class': 'form-select'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Mandatory explanation / approval rationale...')}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
        self.fields['period'].queryset = PayrollPeriod.objects.exclude(
            status__in=[PayrollPeriod.Status.CLOSED, PayrollPeriod.Status.CANCELLED]
        ).order_by('-start_date')


class PayrollTaxRuleForm(forms.ModelForm):
    class Meta:
        model = PayrollTaxRule
        fields = [
            'name',
            'code',
            'percentage',
            'fixed_amount',
            'applies_to',
            'effective_from',
            'effective_to',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'fixed_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'applies_to': forms.Select(attrs={'class': 'form-select'}),
            'effective_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'effective_to': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class KPIPayrollRuleForm(forms.ModelForm):
    class Meta:
        model = KPIPayrollRule
        fields = [
            'name',
            'min_score',
            'max_score',
            'bonus_type',
            'bonus_value',
            'effective_from',
            'effective_to',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'min_score': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'max_score': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bonus_type': forms.Select(attrs={'class': 'form-select'}),
            'bonus_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'effective_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'effective_to': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MarkPaidForm(forms.Form):
    payment_reference = forms.CharField(
        label=_('Payment Document / Reference'),
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. Bank Batch #202610-01')}),
    )
