from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from organization.models import Department, DepartmentResponsibility, Position


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. Information Technology')}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. IT')}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class DepartmentHeadAssignForm(forms.Form):
    head = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label=_('Department Head'),
        empty_label=_('-- No Head Assigned --'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        if department:
            # Show users of this department or all users with DEPARTMENT_HEAD / EMPLOYEE role
            self.fields['head'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
            if department.head:
                self.fields['head'].initial = department.head


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ['name', 'code', 'description', 'department', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. Senior Developer')}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. SNR_DEV')}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class DepartmentResponsibilityForm(forms.ModelForm):
    class Meta:
        model = DepartmentResponsibility
        fields = ['vice_rector', 'department', 'start_date']
        widgets = {
            'vice_rector': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vice_rector'].queryset = User.objects.filter(
            roles__code=Role.Codes.VICE_RECTOR,
            is_active=True,
        ).distinct().order_by('first_name', 'last_name', 'username')
        self.fields['department'].queryset = Department.objects.filter(is_active=True).order_by('name')
