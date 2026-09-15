from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from accounts.models import Role, User
from hr.forms import EmployeeCreateForm, EmployeeEditForm, EmployeeGradeForm, HRPermissionConfigForm
from hr.models import EmployeeGrade, HRPermissionConfig
from hr.permissions import HRPermissionRequiredMixin, HRRequiredMixin, ScopedEmployeeProfileAccessMixin
from hr.services import (
    activate_employee,
    configure_hr_authority,
    create_employee,
    create_grade,
    deactivate_employee,
    get_hr_permission,
    update_employee,
    update_grade,
)
from kpi.services import calculate_user_kpi_summary
from organization.models import Department, Position
from tasks.models import Task, TaskAssignment


class HROverviewView(LoginRequiredMixin, HRRequiredMixin, ListView):
    model = User
    template_name = 'hr/overview.html'
    context_object_name = 'employees'
    paginate_by = 20

    def get_queryset(self):
        qs = User.objects.select_related('department', 'position', 'grade', 'supervisor').prefetch_related('roles').order_by('last_name', 'first_name')
        if not self.request.user.is_superuser:
            qs = qs.exclude(is_superuser=True)

        q = self.request.GET.get('q', '').strip()
        dept_id = self.request.GET.get('department', '').strip()
        pos_id = self.request.GET.get('position', '').strip()
        grade_id = self.request.GET.get('grade', '').strip()
        status = self.request.GET.get('status', '').strip()

        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(username__icontains=q) |
                Q(email__icontains=q)
            )
        if dept_id:
            qs = qs.filter(department_id=dept_id)
        if pos_id:
            qs = qs.filter(position_id=pos_id)
        if grade_id:
            qs = qs.filter(grade_id=grade_id)
        if status:
            qs = qs.filter(employment_status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_users = User.objects.all()
        if not self.request.user.is_superuser:
            all_users = all_users.exclude(is_superuser=True)
        context['stats'] = {
            'total': all_users.count(),
            'active': all_users.filter(employment_status=User.EmploymentStatus.ACTIVE).count(),
            'on_leave': all_users.filter(employment_status=User.EmploymentStatus.ON_LEAVE).count(),
            'inactive': all_users.filter(employment_status=User.EmploymentStatus.INACTIVE).count(),
        }
        context['departments'] = Department.objects.filter(is_active=True)
        context['positions'] = Position.objects.filter(is_active=True)
        context['grades'] = EmployeeGrade.objects.filter(is_active=True)
        context['statuses'] = User.EmploymentStatus.choices
        context['can_create'] = self.request.user.is_superuser or self.request.user.is_rector or get_hr_permission(self.request.user, 'can_create_employees')
        return context


class EmployeeProfileView(LoginRequiredMixin, ScopedEmployeeProfileAccessMixin, DetailView):
    model = User
    template_name = 'hr/employee_profile.html'
    context_object_name = 'employee'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        emp = self.object
        viewer = self.request.user

        # Organizational supervisor chain
        supervisor = emp.supervisor
        subordinates = emp.subordinates.filter(is_active=True).select_related('position', 'department')
        context['supervisor'] = supervisor
        context['subordinates'] = subordinates

        # KPI Summary
        context['kpi_summary'] = calculate_user_kpi_summary(emp)

        # Recent Task Assignments
        context['recent_assignments'] = TaskAssignment.objects.filter(user=emp).select_related('task', 'task__responsible_department').order_by('-created_at')[:8]

        # Authority checks for actions
        context['can_edit'] = viewer.is_superuser or get_hr_permission(viewer, 'can_edit_employees') or viewer.id == emp.id
        context['can_deactivate'] = (viewer.is_superuser or get_hr_permission(viewer, 'can_deactivate_employees')) and viewer.id != emp.id
        return context


class EmployeeCreateView(LoginRequiredMixin, HRRequiredMixin, View):
    template_name = 'hr/employee_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not (request.user.is_superuser or get_hr_permission(request.user, 'can_create_employees')):
            raise PermissionDenied(_('You do not have permission to create employees.'))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = EmployeeCreateForm()
        return render(request, self.template_name, {'form': form, 'is_create': True})

    def post(self, request):
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            try:
                emp = create_employee(request.user, form.cleaned_data, request=request)
                messages.success(request, _('Employee %(name)s created successfully.') % {'name': emp.display_name})
                return redirect('hr:employee_profile', pk=emp.pk)
            except Exception as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'is_create': True})


class EmployeeEditView(LoginRequiredMixin, ScopedEmployeeProfileAccessMixin, View):
    template_name = 'hr/employee_form.html'

    def dispatch(self, request, *args, **kwargs):
        user = self.get_target_user()
        if not (request.user.is_superuser or get_hr_permission(request.user, 'can_edit_employees') or request.user.id == user.id):
            raise PermissionDenied(_('You do not have permission to edit this employee.'))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        emp = self.get_target_user()
        form = EmployeeEditForm(instance=emp)
        return render(request, self.template_name, {'form': form, 'employee': emp, 'is_create': False})

    def post(self, request, pk):
        emp = self.get_target_user()
        form = EmployeeEditForm(request.POST, instance=emp)
        if form.is_valid():
            try:
                update_employee(request.user, emp, form.cleaned_data, request=request)
                messages.success(request, _('Employee profile updated successfully.'))
                return redirect('hr:employee_profile', pk=emp.pk)
            except Exception as e:
                messages.error(request, str(e))
        return render(request, self.template_name, {'form': form, 'employee': emp, 'is_create': False})


class EmployeeToggleStatusView(LoginRequiredMixin, HRRequiredMixin, View):
    def post(self, request, pk):
        emp = get_object_or_404(User, pk=pk)
        if emp.is_active:
            deactivate_employee(request.user, emp, request=request)
            messages.warning(request, _('Employee %(name)s has been deactivated.') % {'name': emp.display_name})
        else:
            activate_employee(request.user, emp, request=request)
            messages.success(request, _('Employee %(name)s has been activated.') % {'name': emp.display_name})
        return redirect('hr:employee_profile', pk=emp.pk)


class EmployeeGradeListView(LoginRequiredMixin, HRRequiredMixin, ListView):
    model = EmployeeGrade
    template_name = 'hr/grade_list.html'
    context_object_name = 'grades'

    def get_queryset(self):
        return EmployeeGrade.objects.annotate(employee_count=Count('users')).order_by('rank', 'code')


class EmployeeGradeCreateView(LoginRequiredMixin, HRRequiredMixin, CreateView):
    model = EmployeeGrade
    form_class = EmployeeGradeForm
    template_name = 'hr/grade_form.html'
    success_url = reverse_lazy('hr:grade_list')

    def form_valid(self, form):
        create_grade(self.request.user, form.cleaned_data, request=self.request)
        messages.success(self.request, _('Employee grade created successfully.'))
        return redirect(self.success_url)


class EmployeeGradeEditView(LoginRequiredMixin, HRRequiredMixin, UpdateView):
    model = EmployeeGrade
    form_class = EmployeeGradeForm
    template_name = 'hr/grade_form.html'
    success_url = reverse_lazy('hr:grade_list')

    def form_valid(self, form):
        update_grade(self.request.user, self.object, form.cleaned_data, request=self.request)
        messages.success(self.request, _('Employee grade updated successfully.'))
        return redirect(self.success_url)


class HRPermissionConfigView(LoginRequiredMixin, View):
    template_name = 'hr/permissions_config.html'

    def dispatch(self, request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.is_rector):
            raise PermissionDenied(_('Only the Rector or Technical Superadmin can configure HR authority permissions.'))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        hr_users = User.objects.filter(roles__code=Role.Codes.HR, is_active=True).distinct()
        authorities = {u.id: getattr(u, 'hr_authority', None) for u in hr_users}
        return render(request, self.template_name, {
            'hr_users': hr_users,
            'authorities': authorities,
        })

    def post(self, request):
        user_id = request.POST.get('user_id')
        target_user = get_object_or_404(User, pk=user_id)

        form = HRPermissionConfigForm(request.POST)
        if form.is_valid():
            configure_hr_authority(request.user, target_user, form.cleaned_data, request=request)
            messages.success(request, _('HR authority permissions updated for %(user)s.') % {'user': target_user.display_name})
        else:
            messages.error(request, _('Invalid permission configuration.'))

        return redirect('hr:permissions_config')


class HRDepartmentOptionsAPIView(LoginRequiredMixin, HRRequiredMixin, View):
    """
    Returns JSON filtered lists of compatible Positions and eligible Supervisors
    when a Department is selected on the Employee form.
    """
    def get(self, request):
        from django.http import JsonResponse
        from hr.services import get_eligible_supervisors

        dept_id = request.GET.get('department_id', '').strip()
        exclude_user_id = request.GET.get('exclude_user_id', '').strip()

        dept = None
        if dept_id:
            try:
                dept = Department.objects.get(pk=dept_id, is_active=True)
            except (Department.DoesNotExist, ValueError):
                dept = None

        exclude_user = None
        if exclude_user_id:
            try:
                exclude_user = User.objects.get(pk=exclude_user_id)
            except (User.DoesNotExist, ValueError):
                exclude_user = None

        # 1. Compatible Positions
        if dept:
            positions = Position.objects.filter(
                is_active=True
            ).filter(Q(department=dept) | Q(department__isnull=True)).order_by('name')
        else:
            positions = Position.objects.filter(is_active=True).order_by('name')

        pos_data = [
            {'id': str(p.id), 'name': f"{p.name} ({p.department.code})" if p.department else p.name}
            for p in positions
        ]

        # 2. Eligible Supervisors
        supervisors = get_eligible_supervisors(department=dept, exclude_user=exclude_user)
        sup_data = []
        for s in supervisors:
            pos_label = s.position.name if s.position else (s.primary_role.name if s.primary_role else _('Management'))
            dept_label = s.department.name if s.department else _('University Leadership')
            sup_data.append({
                'id': str(s.id),
                'label': f"{s.display_name} — {pos_label} ({dept_label})"
            })

        return JsonResponse({
            'positions': pos_data,
            'supervisors': sup_data,
        })

