from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from accounts.models import Role, User
from accounts.permissions import RectorRequiredMixin, ScopedDepartmentAccessMixin
from core.models import AuditLog, log_audit
from organization.forms import (
    ActingRectorDelegationForm,
    DepartmentForm,
    DepartmentHeadAssignForm,
    DepartmentResponsibilityForm,
    PositionForm,
)
from organization.models import ActingRectorDelegation, Department, DepartmentResponsibility, Position
from organization.services import (
    assign_acting_rector,
    assign_department_head,
    assign_vice_rector_responsibility,
    remove_vice_rector_responsibility,
    revoke_acting_rector,
)


class OrganizationOverviewView(LoginRequiredMixin, TemplateView):
    template_name = 'organization/overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        from django.utils import timezone

        # Fetch Rector (strictly university leadership, exclude superadmin)
        rector_role = Role.objects.filter(code=Role.Codes.RECTOR).first()
        rectors = User.objects.filter(
            roles=rector_role,
            is_superuser=False,
            is_active=True,
        ).distinct()

        # Fetch Vice Rectors (strictly university leadership, exclude superadmin)
        vr_role = Role.objects.filter(code=Role.Codes.VICE_RECTOR).first()
        vice_rectors_qs = User.objects.filter(
            roles=vr_role,
            is_superuser=False,
            is_active=True,
        ).distinct().prefetch_related(
            'department_responsibilities__department',
            'department_responsibilities__department__head',
        )

        # Active Acting Rector delegation (if any)
        today = timezone.now().date()
        active_delegation = ActingRectorDelegation.objects.filter(
            is_active=True,
            start_date__lte=today,
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        ).select_related('acting_rector', 'acting_rector__position', 'rector').first()

        # Scoped view for departments
        scoped_depts = user.get_scoped_departments().filter(is_active=True).select_related('head').prefetch_related('users')

        context['rectors'] = rectors
        context['vice_rectors'] = vice_rectors_qs
        context['scoped_departments'] = scoped_depts
        context['active_delegation'] = active_delegation
        context['delegation_form'] = (
            ActingRectorDelegationForm() if (user.is_rector or user.is_superuser) else None
        )
        return context


class DepartmentListView(LoginRequiredMixin, ListView):
    model = Department
    template_name = 'organization/department_list.html'
    context_object_name = 'departments'
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        qs = user.get_scoped_departments().select_related('head').prefetch_related(
            'vice_rector_responsibilities__vice_rector',
            'users',
        )

        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(description__icontains=query))

        status = self.request.GET.get('status', '').strip()
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['total_departments'] = self.get_queryset().count()
        return context


class DepartmentDetailView(ScopedDepartmentAccessMixin, DetailView):
    model = Department
    template_name = 'organization/department_detail.html'
    context_object_name = 'department'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        department = self.object
        employees = department.users.select_related('position').prefetch_related('roles').order_by('first_name', 'last_name')
        if not self.request.user.is_superuser:
            employees = employees.exclude(is_superuser=True)
        positions = department.positions.filter(is_active=True).order_by('name')
        active_responsibilities = department.vice_rector_responsibilities.filter(
            is_active=True,
        ).select_related('vice_rector')

        context['employees'] = employees
        context['positions'] = positions
        context['active_responsibilities'] = active_responsibilities
        context['head_form'] = DepartmentHeadAssignForm(department=department) if (self.request.user.is_rector or self.request.user.is_superuser) else None
        return context


class DepartmentCreateView(RectorRequiredMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'organization/department_form.html'
    success_url = reverse_lazy('department_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        log_audit(
            actor=self.request.user,
            action=AuditLog.Actions.DEPARTMENT_CREATED,
            target_repr=self.object.name,
            details={'code': self.object.code, 'is_active': self.object.is_active},
            request=self.request,
        )
        messages.success(self.request, _('Department "%(name)s" created successfully.') % {'name': self.object.name})
        return response


class DepartmentUpdateView(RectorRequiredMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'organization/department_form.html'

    def get_success_url(self):
        return reverse('department_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        log_audit(
            actor=self.request.user,
            action=AuditLog.Actions.DEPARTMENT_UPDATED,
            target_repr=self.object.name,
            details={'code': self.object.code, 'is_active': self.object.is_active},
            request=self.request,
        )
        messages.success(self.request, _('Department "%(name)s" updated successfully.') % {'name': self.object.name})
        return response


class DepartmentToggleActiveView(RectorRequiredMixin, View):
    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        department.is_active = not department.is_active
        department.save(update_fields=['is_active', 'updated_at'])

        action_label = _('activated') if department.is_active else _('deactivated')
        log_audit(
            actor=request.user,
            action=AuditLog.Actions.DEPARTMENT_UPDATED,
            target_repr=department.name,
            details={'is_active': department.is_active},
            request=request,
        )
        messages.success(request, _('Department "%(name)s" was %(action)s.') % {'name': department.name, 'action': action_label})
        return redirect('department_detail', pk=department.pk)


class DepartmentAssignHeadView(RectorRequiredMixin, View):
    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        form = DepartmentHeadAssignForm(request.POST, department=department)
        if form.is_valid():
            head_user = form.cleaned_data.get('head')
            assign_department_head(department, head_user, actor=request.user, request=request)
            if head_user:
                messages.success(request, _('%(user)s assigned as Head of %(dept)s.') % {'user': head_user.display_name, 'dept': department.name})
            else:
                messages.info(request, _('Department Head removed for %(dept)s.') % {'dept': department.name})
        else:
            messages.error(request, _('Invalid form submission for assigning department head.'))
        return redirect('department_detail', pk=department.pk)


# --- POSITIONS ---

class PositionListView(RectorRequiredMixin, ListView):
    model = Position
    template_name = 'organization/position_list.html'
    context_object_name = 'positions'
    paginate_by = 15

    def get_queryset(self):
        qs = Position.objects.select_related('department')
        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(code__icontains=query))
        status = self.request.GET.get('status', '').strip()
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)
        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['status_filter'] = self.request.GET.get('status', '')
        return context


class PositionCreateView(RectorRequiredMixin, CreateView):
    model = Position
    form_class = PositionForm
    template_name = 'organization/position_form.html'
    success_url = reverse_lazy('position_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        log_audit(
            actor=self.request.user,
            action=AuditLog.Actions.POSITION_CREATED,
            target_repr=self.object.name,
            details={'code': self.object.code, 'is_active': self.object.is_active},
            request=self.request,
        )
        messages.success(self.request, _('Position "%(name)s" created successfully.') % {'name': self.object.name})
        return response


class PositionUpdateView(RectorRequiredMixin, UpdateView):
    model = Position
    form_class = PositionForm
    template_name = 'organization/position_form.html'
    success_url = reverse_lazy('position_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        log_audit(
            actor=self.request.user,
            action=AuditLog.Actions.POSITION_UPDATED,
            target_repr=self.object.name,
            details={'code': self.object.code, 'is_active': self.object.is_active},
            request=self.request,
        )
        messages.success(self.request, _('Position "%(name)s" updated successfully.') % {'name': self.object.name})
        return response


class PositionToggleActiveView(RectorRequiredMixin, View):
    def post(self, request, pk):
        position = get_object_or_404(Position, pk=pk)
        position.is_active = not position.is_active
        position.save(update_fields=['is_active', 'updated_at'])

        action_label = _('activated') if position.is_active else _('deactivated')
        log_audit(
            actor=request.user,
            action=AuditLog.Actions.POSITION_UPDATED,
            target_repr=position.name,
            details={'is_active': position.is_active},
            request=request,
        )
        messages.success(request, _('Position "%(name)s" was %(action)s.') % {'name': position.name, 'action': action_label})
        return redirect('position_list')


# --- VICE RECTOR RESPONSIBILITY ---

class ViceRectorResponsibilityListView(RectorRequiredMixin, TemplateView):
    template_name = 'organization/responsibility_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vr_role = Role.objects.filter(code=Role.Codes.VICE_RECTOR).first()
        vice_rectors = User.objects.filter(
            roles=vr_role,
            is_active=True,
        ).distinct().prefetch_related(
            'department_responsibilities__department',
        )

        all_responsibilities = DepartmentResponsibility.objects.filter(
            is_active=True,
        ).select_related('vice_rector', 'department').order_by('vice_rector__username', 'department__name')

        context['vice_rectors'] = vice_rectors
        context['all_responsibilities'] = all_responsibilities
        context['assign_form'] = DepartmentResponsibilityForm()
        return context


class ViceRectorResponsibilityCreateView(RectorRequiredMixin, View):
    def post(self, request):
        form = DepartmentResponsibilityForm(request.POST)
        if form.is_valid():
            vice_rector = form.cleaned_data['vice_rector']
            department = form.cleaned_data['department']
            start_date = form.cleaned_data.get('start_date')
            assign_vice_rector_responsibility(
                vice_rector=vice_rector,
                department=department,
                actor=request.user,
                start_date=start_date,
                request=request,
            )
            messages.success(
                request,
                _('Assigned %(dept)s to Vice Rector %(vr)s.') % {
                    'dept': department.name,
                    'vr': vice_rector.display_name,
                },
            )
        else:
            messages.error(request, _('Could not assign responsibility. Please check the form.'))
        return redirect('responsibility_list')


class ViceRectorResponsibilityDeleteView(RectorRequiredMixin, View):
    def post(self, request, pk):
        resp = get_object_or_404(DepartmentResponsibility, pk=pk)
        remove_vice_rector_responsibility(resp, actor=request.user, request=request)
        messages.info(
            request,
            _('Removed responsibility for %(dept)s from Vice Rector %(vr)s.') % {
                'dept': resp.department.name,
                'vr': resp.vice_rector.display_name,
            },
        )
        return redirect('responsibility_list')


class ActingRectorAssignView(RectorRequiredMixin, View):
    """POST: Rector or Superadmin designates a Vice Rector as Acting Rector."""

    def post(self, request):
        form = ActingRectorDelegationForm(request.POST)
        if form.is_valid():
            acting_rector = form.cleaned_data['acting_rector']
            start_date = form.cleaned_data['start_date']
            end_date = form.cleaned_data.get('end_date')
            reason = form.cleaned_data.get('reason', '')
            try:
                delegation = assign_acting_rector(
                    rector=request.user,
                    acting_rector=acting_rector,
                    actor=request.user,
                    start_date=start_date,
                    end_date=end_date,
                    reason=reason,
                    request=request,
                )
                messages.success(
                    request,
                    _('Successfully assigned %(vr)s as Acting Rector.') % {'vr': acting_rector.display_name},
                )
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
        else:
            messages.error(request, _('Please correct the errors in the delegation form.'))
        return redirect('organization_overview')


class ActingRectorRevokeView(RectorRequiredMixin, View):
    """POST: Rector or Superadmin revokes an active Acting Rector delegation."""

    def post(self, request, pk):
        delegation = get_object_or_404(ActingRectorDelegation, pk=pk)
        revoke_acting_rector(delegation, actor=request.user, request=request)
        messages.info(
            request,
            _('Revoked Acting Rector duties from %(vr)s.') % {'vr': delegation.acting_rector.display_name},
        )
        return redirect('organization_overview')
