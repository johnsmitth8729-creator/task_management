from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.views.generic import ListView, TemplateView, View

from accounts.models import Role, User
from accounts.permissions import RectorRequiredMixin
from core.models import AuditLog
from organization.models import Department, DepartmentResponsibility, Position


class HomeRedirectView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return redirect('login')


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'core/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_rector:
            context['total_departments'] = Department.objects.count()
            context['active_departments'] = Department.objects.filter(is_active=True).count()
            context['total_users'] = User.objects.count()
            context['active_users'] = User.objects.filter(is_active=True).count()
            context['inactive_users'] = User.objects.filter(is_active=False).count()
            context['total_positions'] = Position.objects.count()

            vr_role = Role.objects.filter(code=Role.Codes.VICE_RECTOR).first()
            context['total_vice_rectors'] = User.objects.filter(roles=vr_role, is_active=True).count() if vr_role else 0

            head_role = Role.objects.filter(code=Role.Codes.DEPARTMENT_HEAD).first()
            context['total_department_heads'] = User.objects.filter(roles=head_role, is_active=True).count() if head_role else 0

            emp_role = Role.objects.filter(code=Role.Codes.EMPLOYEE).first()
            context['total_employees'] = User.objects.filter(roles=emp_role, is_active=True).count() if emp_role else 0

            context['recent_audit_logs'] = AuditLog.objects.select_related('actor')[:8]
            context['departments_summary'] = Department.objects.filter(is_active=True).select_related('head').annotate(
                active_employee_count=Count('users', filter=Q(users__is_active=True)),
            ).order_by('-active_employee_count')[:6]

        elif user.is_vice_rector:
            scoped_depts = user.get_scoped_departments().filter(is_active=True).select_related('head').annotate(
                active_employee_count=Count('users', filter=Q(users__is_active=True)),
            )
            context['my_departments'] = scoped_depts
            context['total_scoped_departments'] = scoped_depts.count()
            scoped_users = user.get_scoped_users().filter(is_active=True)
            context['total_scoped_employees'] = scoped_users.count()
            context['scoped_department_heads'] = scoped_users.filter(roles__code=Role.Codes.DEPARTMENT_HEAD)

        elif user.is_department_head and user.department:
            dept = user.department
            context['my_department'] = dept
            context['department_employees'] = dept.users.filter(is_active=True).select_related('position').order_by('first_name', 'last_name')
            context['department_positions'] = dept.positions.filter(is_active=True)
            context['total_department_employees'] = dept.users.filter(is_active=True).count()
            context['active_responsibilities'] = dept.vice_rector_responsibilities.filter(is_active=True).select_related('vice_rector')

        else:
            # Standard Employee
            context['my_department'] = user.department
            context['my_position'] = user.position

        return context


class AuditLogListView(RectorRequiredMixin, ListView):
    model = AuditLog
    template_name = 'core/audit_list.html'
    context_object_name = 'audit_logs'
    paginate_by = 20

    def get_queryset(self):
        qs = AuditLog.objects.select_related('actor')
        action_filter = self.request.GET.get('action', '').strip()
        if action_filter:
            qs = qs.filter(action=action_filter)
        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(target_repr__icontains=query)
                | Q(actor__username__icontains=query)
                | Q(actor__first_name__icontains=query)
                | Q(actor__last_name__icontains=query)
            )
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['actions'] = AuditLog.Actions.choices
        context['selected_action'] = self.request.GET.get('action', '')
        context['search_query'] = self.request.GET.get('q', '')
        return context
