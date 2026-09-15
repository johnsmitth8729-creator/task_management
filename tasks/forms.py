from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from organization.models import Department
from tasks.models import (
    RecurringTask,
    SubTask,
    Task,
    TaskDependency,
    TaskTemplate,
    TaskType,
)


class TaskCreateForm(forms.ModelForm):
    secondary_departments = forms.ModelMultipleChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label=_('Additional Departments'),
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2-enable'}),
        help_text=_('Optional additional departments involved in this task.'),
    )
    initial_assignees = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        label=_('Initial Assignees'),
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2-enable'}),
        help_text=_('Hold Ctrl (or Cmd) to select multiple employees.'),
    )
    primary_assignee = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label=_('Primary Assignee'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_('Optional main responsible employee.'),
    )

    class Meta:
        model = Task
        fields = [
            'title',
            'description',
            'responsible_department',
            'task_type',
            'priority',
            'complexity',
            'start_date',
            'deadline',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Enter task title...')}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': _('Detailed task description, objectives, and requirements...')}),
            'responsible_department': forms.Select(attrs={'class': 'form-select'}),
            'task_type': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'complexity': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.user = user
        super().__init__(*args, **kwargs)

        self.fields['task_type'].queryset = TaskType.objects.filter(is_active=True).order_by('name')

        if user:
            is_super = user.is_superuser
            can_rector = user.is_superuser or user.can_act_as_rector

            if can_rector:
                self.fields['responsible_department'].label = _('Primary Responsible Department')
                self.fields['responsible_department'].queryset = Department.objects.filter(is_active=True).order_by('name')
                self.fields['secondary_departments'].queryset = Department.objects.filter(is_active=True).order_by('name')
                assignees_qs = User.objects.filter(is_active=True)
                if not is_super:
                    assignees_qs = assignees_qs.exclude(is_superuser=True)
                self.fields['initial_assignees'].queryset = assignees_qs.select_related('department', 'position').order_by('first_name', 'last_name')
                self.fields['primary_assignee'].queryset = self.fields['initial_assignees'].queryset
            elif user.is_vice_rector:
                scoped_depts = user.get_scoped_departments().filter(is_active=True).order_by('name')
                self.fields['responsible_department'].label = _('Primary Responsible Department')
                self.fields['responsible_department'].queryset = scoped_depts
                self.fields['secondary_departments'].queryset = scoped_depts
                assignees_qs = User.objects.filter(department__in=scoped_depts, is_active=True).exclude(is_superuser=True)
                assignees_qs = assignees_qs.exclude(roles__code__in=[Role.Codes.RECTOR, Role.Codes.VICE_RECTOR])
                self.fields['initial_assignees'].queryset = assignees_qs.select_related('department', 'position').order_by('first_name', 'last_name')
                self.fields['primary_assignee'].queryset = self.fields['initial_assignees'].queryset
            elif user.is_department_head and user.department:
                self.fields['responsible_department'].queryset = Department.objects.filter(id=user.department_id)
                self.fields['responsible_department'].initial = user.department
                self.fields['secondary_departments'].queryset = Department.objects.none()
                self.fields['secondary_departments'].widget = forms.HiddenInput()
                assignees_qs = User.objects.filter(department=user.department, is_active=True).exclude(is_superuser=True)
                assignees_qs = assignees_qs.exclude(roles__code__in=[Role.Codes.RECTOR, Role.Codes.VICE_RECTOR, Role.Codes.DEPARTMENT_HEAD])
                self.fields['initial_assignees'].queryset = assignees_qs.select_related('department', 'position').order_by('first_name', 'last_name')
                self.fields['primary_assignee'].queryset = self.fields['initial_assignees'].queryset

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        deadline = cleaned_data.get('deadline')
        dept = cleaned_data.get('responsible_department')
        secondary_depts = list(cleaned_data.get('secondary_departments') or [])
        assignees = cleaned_data.get('initial_assignees')
        primary = cleaned_data.get('primary_assignee')

        if start_date and deadline and start_date > deadline:
            self.add_error('deadline', _('Deadline cannot be before start date.'))

        # Filter out primary department from secondary departments if present
        if dept and secondary_depts and dept in secondary_depts:
            secondary_depts = [d for d in secondary_depts if d.id != dept.id]
            cleaned_data['secondary_departments'] = secondary_depts

        if primary and assignees and primary not in assignees:
            self.add_error('primary_assignee', _('Primary assignee must be one of the selected assignees.'))

        # Check department boundary only for Department Head and Vice Rector; Rector can assign cross-department!
        if self.user and not (self.user.is_superuser or self.user.can_act_as_rector):
            if assignees:
                for u in assignees:
                    if self.user.is_department_head and u.department_id != self.user.department_id:
                        self.add_error('initial_assignees', _(f"Employee {u.display_name} does not belong to {self.user.department.name}."))
                    elif self.user.is_vice_rector:
                        scoped_depts = self.user.get_scoped_departments()
                        if u.department_id and not scoped_depts.filter(id=u.department_id).exists():
                            self.add_error('initial_assignees', _(f"Employee {u.display_name} is outside your departmental scope."))

        return cleaned_data


class TaskUpdateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            'title',
            'description',
            'responsible_department',
            'task_type',
            'priority',
            'complexity',
            'progress',
            'start_date',
            'deadline',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'responsible_department': forms.Select(attrs={'class': 'form-select'}),
            'task_type': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'complexity': forms.Select(attrs={'class': 'form-select'}),
            'progress': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['task_type'].queryset = TaskType.objects.filter(is_active=True).order_by('name')

        if user:
            if user.is_superuser or user.can_act_as_rector:
                self.fields['responsible_department'].queryset = Department.objects.filter(is_active=True).order_by('name')
            elif user.is_vice_rector:
                self.fields['responsible_department'].queryset = user.get_scoped_departments().filter(is_active=True).order_by('name')
            elif user.is_department_head and user.department:
                self.fields['responsible_department'].queryset = Department.objects.filter(id=user.department_id)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        deadline = cleaned_data.get('deadline')
        progress = cleaned_data.get('progress')

        if start_date and deadline and start_date > deadline:
            self.add_error('deadline', _('Deadline cannot be earlier than start date.'))

        if progress is not None and (progress < 0 or progress > 100):
            self.add_error('progress', _('Progress must be between 0 and 100.'))

        return cleaned_data


class TaskAssignForm(forms.Form):
    assignees = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label=_('Assigned Employees'),
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2-enable'}),
        help_text=_('Select one or more employees from the responsible department.'),
    )
    primary_assignee = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label=_('Primary Assignee'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_('Select the main responsible person (optional).'),
    )

    def __init__(self, *args, **kwargs):
        task = kwargs.pop('task')
        self.task = task
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        user = self.user
        is_super = user.is_superuser if user else False
        can_rector = user and (user.is_superuser or user.can_act_as_rector)

        if can_rector:
            assignees_qs = User.objects.filter(is_active=True)
            if not is_super:
                assignees_qs = assignees_qs.exclude(is_superuser=True)
        elif user and user.is_vice_rector:
            scoped_depts = user.get_scoped_departments()
            assignees_qs = User.objects.filter(department__in=scoped_depts, is_active=True).exclude(is_superuser=True)
            assignees_qs = assignees_qs.exclude(roles__code__in=[Role.Codes.RECTOR, Role.Codes.VICE_RECTOR])
        elif user and user.is_department_head and user.department:
            assignees_qs = User.objects.filter(department=user.department, is_active=True).exclude(is_superuser=True)
            assignees_qs = assignees_qs.exclude(roles__code__in=[Role.Codes.RECTOR, Role.Codes.VICE_RECTOR, Role.Codes.DEPARTMENT_HEAD])
        elif task.responsible_department:
            assignees_qs = task.responsible_department.users.filter(is_active=True).exclude(is_superuser=True)
        else:
            assignees_qs = User.objects.filter(is_active=True).exclude(is_superuser=True)

        self.fields['assignees'].queryset = assignees_qs.order_by('first_name', 'last_name')
        self.fields['primary_assignee'].queryset = self.fields['assignees'].queryset
        format_label = lambda u: f"{u.display_name} ({u.username})" if u.display_name != u.username else u.username
        self.fields['assignees'].label_from_instance = format_label
        self.fields['primary_assignee'].label_from_instance = format_label

        # Set initial values from existing assignments
        existing_assignee_ids = list(task.assignments.values_list('user_id', flat=True))
        primary_id = task.assignments.filter(is_primary=True).values_list('user_id', flat=True).first()
        self.fields['assignees'].initial = existing_assignee_ids
        if primary_id:
            self.fields['primary_assignee'].initial = primary_id

    def clean(self):
        cleaned_data = super().clean()
        assignees = cleaned_data.get('assignees')
        primary = cleaned_data.get('primary_assignee')

        if primary and assignees and primary not in assignees:
            self.add_error('primary_assignee', _('The primary assignee must be among the assigned employees.'))

        # Ensure no protected assignments are dropped
        if self.user and self.task and assignees is not None:
            from tasks.permissions import can_unassign_user
            for assignment in self.task.assignments.select_related('user', 'assigned_by').all():
                if assignment.user not in assignees:
                    if not can_unassign_user(self.user, self.task, assignment):
                        if assignment.user_id == self.user.id:
                            self.add_error(
                                'assignees',
                                _("Biriktirilgan xodim o'zini vazifadan chiqara olmaydi.")
                            )
                        else:
                            assigner_name = assignment.assigned_by.display_name if assignment.assigned_by else _("rahbariyat")
                            self.add_error(
                                'assignees',
                                _(f"{assignment.user.display_name} xodimini vazifadan chiqara olmaysiz (u {assigner_name} tomonidan biriktirilgan).")
                            )

        return cleaned_data


class TaskCancelForm(forms.Form):
    cancellation_reason = forms.CharField(
        label=_('Cancellation Reason'),
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': _('Please provide a detailed reason for cancelling this task...'),
            'required': True,
        }),
        help_text=_('This reason will be recorded in the task history and audit trail.'),
    )


class SubTaskForm(forms.ModelForm):
    class Meta:
        model = SubTask
        fields = ['title', 'description', 'status', 'progress', 'assignee', 'deadline']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Subtask title...')}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'progress': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'assignee': forms.Select(attrs={'class': 'form-select'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        task = kwargs.pop('task', None)
        super().__init__(*args, **kwargs)
        if task and task.responsible_department:
            self.fields['assignee'].queryset = task.responsible_department.users.filter(is_active=True).order_by('first_name', 'last_name')
        else:
            self.fields['assignee'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name')


class TaskDependencyForm(forms.ModelForm):
    class Meta:
        model = TaskDependency
        fields = ['depends_on', 'dependency_type']
        widgets = {
            'depends_on': forms.Select(attrs={'class': 'form-select'}),
            'dependency_type': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        task = kwargs.pop('task')
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        from tasks.services import get_scoped_tasks
        # Exclude current task, already dependent tasks, and archived tasks
        existing_dep_ids = list(task.dependencies.values_list('depends_on_id', flat=True)) + [task.id]
        self.fields['depends_on'].queryset = get_scoped_tasks(user).exclude(id__in=existing_dep_ids).order_by('task_number')


class TaskTypeForm(forms.ModelForm):
    class Meta:
        model = TaskType
        fields = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. WEB_DEV'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TaskTemplateForm(forms.ModelForm):
    class Meta:
        model = TaskTemplate
        fields = ['name', 'description', 'task_type', 'default_priority', 'default_complexity', 'default_duration_days', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'task_type': forms.Select(attrs={'class': 'form-select'}),
            'default_priority': forms.Select(attrs={'class': 'form-select'}),
            'default_complexity': forms.Select(attrs={'class': 'form-select'}),
            'default_duration_days': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '14'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TaskFromTemplateForm(forms.Form):
    title = forms.CharField(
        label=_('Task Title'),
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    responsible_department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label=_('Responsible Department'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    deadline = forms.DateField(
        label=_('Deadline'),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        template = kwargs.pop('template')
        super().__init__(*args, **kwargs)

        if user.is_rector:
            self.fields['responsible_department'].queryset = Department.objects.filter(is_active=True).order_by('name')
        elif user.is_vice_rector:
            self.fields['responsible_department'].queryset = user.get_scoped_departments().filter(is_active=True).order_by('name')

        self.fields['title'].initial = template.name
