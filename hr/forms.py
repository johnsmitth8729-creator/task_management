from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from hr.models import EmployeeGrade, HRPermissionConfig
from hr.services import get_eligible_supervisors, validate_supervisor_assignment
from organization.models import Department, Position


class SupervisorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        pos_name = obj.position.name if obj.position else (obj.primary_role.name if obj.primary_role else _('Management'))
        dept_name = obj.department.name if obj.department else _('University Leadership')
        return f"{obj.display_name} — {pos_name} ({dept_name})"


class EmployeeCreateForm(forms.Form):
    username = forms.CharField(
        label=_('Username'),
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. john.doe'}),
    )
    email = forms.EmailField(
        label=_('Email Address'),
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'e.g. john@university.test'}),
    )
    first_name = forms.CharField(
        label=_('First Name'),
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    last_name = forms.CharField(
        label=_('Last Name'),
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    phone = forms.CharField(
        label=_('Phone Number'),
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+998 90 123 45 67'}),
    )
    department = forms.ModelChoiceField(
        label=_('Department'),
        queryset=Department.objects.filter(is_active=True),
        required=False,
        empty_label=_('-- University-Wide / Unassigned --'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_department'}),
    )
    position = forms.ModelChoiceField(
        label=_('Position'),
        queryset=Position.objects.filter(is_active=True),
        required=False,
        empty_label=_('-- Select Position --'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_position'}),
    )
    grade = forms.ModelChoiceField(
        label=_('Grade / Level'),
        queryset=EmployeeGrade.objects.filter(is_active=True),
        required=False,
        empty_label=_('-- Select Grade --'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    supervisor = SupervisorChoiceField(
        label=_('Direct Supervisor'),
        queryset=User.objects.none(),
        required=False,
        empty_label=_('-- No Supervisor (Direct Leadership) --'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_supervisor'}),
    )
    employment_status = forms.ChoiceField(
        label=_('Employment Status'),
        choices=User.EmploymentStatus.choices,
        initial=User.EmploymentStatus.ACTIVE,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    employment_start_date = forms.DateField(
        label=_('Employment Start Date'),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    password = forms.CharField(
        label=_('Temporary Password'),
        initial='ChangeMe12345!',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        dept = department
        if self.data and self.data.get('department'):
            try:
                dept = Department.objects.get(pk=self.data.get('department'), is_active=True)
            except (Department.DoesNotExist, ValueError):
                pass
        self.fields['supervisor'].queryset = get_eligible_supervisors(department=dept)
        if dept:
            self.fields['position'].queryset = Position.objects.filter(
                is_active=True
            ).filter(Q(department=dept) | Q(department__isnull=True))
        else:
            self.fields['position'].queryset = Position.objects.filter(is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        dept = cleaned_data.get('department')
        pos = cleaned_data.get('position')
        supervisor = cleaned_data.get('supervisor')

        if pos and pos.department and dept and pos.department != dept:
            self.add_error(
                'position',
                _('Selected position is assigned to "%(pos_dept)s" and is incompatible with "%(emp_dept)s".')
                % {'pos_dept': pos.department.name, 'emp_dept': dept.name}
            )

        if supervisor:
            try:
                validate_supervisor_assignment(None, supervisor, dept)
            except forms.ValidationError as e:
                self.add_error('supervisor', e)

        return cleaned_data


class EmployeeEditForm(forms.ModelForm):
    supervisor = SupervisorChoiceField(
        label=_('Direct Supervisor'),
        queryset=User.objects.none(),
        required=False,
        empty_label=_('-- No Supervisor (Direct Leadership) --'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_supervisor'}),
    )

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'phone',
            'department',
            'position',
            'grade',
            'supervisor',
            'employment_status',
            'employment_start_date',
            'employment_end_date',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select', 'id': 'id_department'}),
            'position': forms.Select(attrs={'class': 'form-select', 'id': 'id_position'}),
            'grade': forms.Select(attrs={'class': 'form-select'}),
            'employment_status': forms.Select(attrs={'class': 'form-select'}),
            'employment_start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'employment_end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        dept = self.instance.department if self.instance else None
        if self.data and self.data.get('department'):
            try:
                dept = Department.objects.get(pk=self.data.get('department'), is_active=True)
            except (Department.DoesNotExist, ValueError):
                pass

        self.fields['supervisor'].queryset = get_eligible_supervisors(department=dept, exclude_user=self.instance)
        if dept:
            self.fields['position'].queryset = Position.objects.filter(
                is_active=True
            ).filter(Q(department=dept) | Q(department__isnull=True))
        else:
            self.fields['position'].queryset = Position.objects.filter(is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        dept = cleaned_data.get('department')
        pos = cleaned_data.get('position')
        supervisor = cleaned_data.get('supervisor')

        if pos and pos.department and dept and pos.department != dept:
            self.add_error(
                'position',
                _('Selected position is assigned to "%(pos_dept)s" and is incompatible with "%(emp_dept)s".')
                % {'pos_dept': pos.department.name, 'emp_dept': dept.name}
            )

        if supervisor:
            try:
                validate_supervisor_assignment(self.instance, supervisor, dept)
            except forms.ValidationError as e:
                self.add_error('supervisor', e)

        return cleaned_data


class EmployeeGradeForm(forms.ModelForm):
    class Meta:
        model = EmployeeGrade
        fields = ['name', 'code', 'description', 'rank', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Senior Specialist'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. G4'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'rank': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class HRPermissionConfigForm(forms.ModelForm):
    class Meta:
        model = HRPermissionConfig
        fields = [
            'can_view_employees',
            'can_create_employees',
            'can_edit_employees',
            'can_deactivate_employees',
            'can_assign_department',
            'can_assign_position',
            'can_assign_grade',
            'can_assign_supervisor',
            'can_manage_departments',
            'can_assign_department_head',
            'can_assign_vice_rector_responsibility',
            'can_view_kpi',
            'can_manage_kpi',
            'can_approve_kpi',
            'can_view_payroll',
            'can_manage_salary',
            'can_create_adjustment',
            'can_manage_payroll',
            'can_approve_payroll',
            'can_mark_paid',
            'can_view_payroll_reports',
        ]
        widgets = {
            field: forms.CheckboxInput(attrs={'class': 'form-check-input'})
            for field in fields
        }
