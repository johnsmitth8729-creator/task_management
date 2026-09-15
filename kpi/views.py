import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)

from accounts.models import User
from kpi.calculation import recalculate_employee_period_kpis
from kpi.forms import (
    KPIAssignmentForm,
    KPICategoryForm,
    KPICorrectionRequestForm,
    KPIDefinitionForm,
    KPIPeriodForm,
    KPIResultEvaluationForm,
)
from kpi.models import (
    KPIAssignment,
    KPICategory,
    KPICorrectionRequest,
    KPIDefinition,
    KPIPeriod,
    KPIResult,
    KPISnapshot,
)
from kpi.permissions import (
    KPIManageRequiredMixin,
    KPIViewCatalogRequiredMixin,
    ScopedKPIAssignmentAccessMixin,
    can_approve_kpi,
    can_calculate_kpi,
    can_manage_kpi,
    can_rector_approve_kpi,
    can_rector_sign_kpi,
    can_request_kpi_correction,
    can_verify_kpi,
    can_view_kpi_for_user,
)
from kpi.services import (
    approve_kpi_result,
    calculate_department_kpi_summary,
    calculate_kpi_period,
    calculate_university_kpi_summary,
    calculate_user_kpi_summary,
    calculate_vice_rector_kpi_summary,
    close_kpi_period,
    hr_verify_kpi_period,
    rector_approve_kpi_period,
    rector_decide_kpi_correction,
    rector_reject_kpi_period,
    rector_sign_kpi_period,
    record_kpi_result,
    request_kpi_correction,
    submit_kpi_period_for_rector,
)
from organization.models import Department
from signatures.services import verify_signature


class PerformanceDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'kpi/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        period_id = self.request.GET.get('period')

        if period_id:
            period = get_object_or_404(KPIPeriod, pk=period_id)
        else:
            period = (
                KPIPeriod.objects.filter(
                    is_active=True,
                    status__in=[
                        KPIPeriod.Status.OPEN,
                        KPIPeriod.Status.UNDER_REVIEW,
                        KPIPeriod.Status.HR_VERIFIED,
                        KPIPeriod.Status.RECTOR_SIGNED,
                    ],
                ).first()
                or KPIPeriod.objects.filter(is_active=True).order_by('-start_date').first()
            )

        context['current_period'] = period
        context['all_periods'] = KPIPeriod.objects.filter(is_active=True).order_by('-start_date')
        context['can_manage_kpi'] = can_manage_kpi(user)
        context['can_calculate_kpi'] = can_calculate_kpi(user)
        context['can_verify_kpi'] = can_verify_kpi(user)
        context['can_rector_approve'] = can_rector_approve_kpi(user)

        # Scoped dashboard rendering depending on operational role
        if user.is_superuser or user.is_rector or (user.is_hr and not user.is_employee):
            context['view_type'] = 'UNIVERSITY'
            context['university_summary'] = calculate_university_kpi_summary(period)
        elif user.is_vice_rector:
            context['view_type'] = 'VICE_RECTOR'
            context['vice_rector_summary'] = calculate_vice_rector_kpi_summary(user, period)
        elif user.is_department_head and user.department:
            context['view_type'] = 'DEPARTMENT'
            context['department_summary'] = calculate_department_kpi_summary(user.department, period)
        else:
            context['view_type'] = 'EMPLOYEE'
            context['user_summary'] = calculate_user_kpi_summary(user, period)

        # Electronic signature snapshot info if signed
        if period and period.status == KPIPeriod.Status.RECTOR_SIGNED:
            snapshot = getattr(period, 'snapshots', None)
            if snapshot:
                context['latest_snapshot'] = snapshot.first()

        return context


class KPIDefinitionListView(LoginRequiredMixin, KPIViewCatalogRequiredMixin, ListView):
    model = KPIDefinition
    template_name = 'kpi/definition_list.html'
    context_object_name = 'definitions'

    def get_queryset(self):
        return (
            KPIDefinition.objects.select_related(
                'category', 'applicable_department', 'applicable_position', 'applicable_grade'
            )
            .filter(is_active=True)
            .order_by('category__order', 'name')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = KPICategory.objects.filter(is_active=True)
        context['can_manage'] = can_manage_kpi(self.request.user)
        return context


class KPIDefinitionCreateView(LoginRequiredMixin, KPIManageRequiredMixin, CreateView):
    model = KPIDefinition
    form_class = KPIDefinitionForm
    template_name = 'kpi/definition_form.html'
    success_url = reverse_lazy('kpi:definition_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, _('KPI definition created successfully.'))
        return super().form_valid(form)


class KPIDefinitionEditView(LoginRequiredMixin, KPIManageRequiredMixin, UpdateView):
    model = KPIDefinition
    form_class = KPIDefinitionForm
    template_name = 'kpi/definition_form.html'
    success_url = reverse_lazy('kpi:definition_list')

    def form_valid(self, form):
        messages.success(self.request, _('KPI definition updated successfully.'))
        return super().form_valid(form)


class KPIPeriodListView(LoginRequiredMixin, ListView):
    model = KPIPeriod
    template_name = 'kpi/period_list.html'
    context_object_name = 'periods'

    def get_queryset(self):
        return KPIPeriod.objects.all().order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_manage'] = can_manage_kpi(self.request.user)
        context['can_rector'] = can_rector_approve_kpi(self.request.user)
        return context


class KPIPeriodDetailView(LoginRequiredMixin, DetailView):
    model = KPIPeriod
    template_name = 'kpi/period_detail.html'
    context_object_name = 'period'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.object
        user = self.request.user
        context['can_manage'] = can_manage_kpi(user)
        context['can_calculate'] = can_calculate_kpi(user)
        context['can_verify'] = can_verify_kpi(user)
        context['can_rector'] = can_rector_approve_kpi(user)
        context['university_summary'] = calculate_university_kpi_summary(period)
        context['snapshots'] = period.snapshots.all().order_by('-created_at')
        context['signatures'] = period.signatures.filter(status='SIGNED').order_by('-signed_at')
        return context


class KPIPeriodCreateView(LoginRequiredMixin, KPIManageRequiredMixin, CreateView):
    model = KPIPeriod
    form_class = KPIPeriodForm
    template_name = 'kpi/period_form.html'
    success_url = reverse_lazy('kpi:period_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, _('KPI period created successfully.'))
        return super().form_valid(form)


class KPIPeriodCalculateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(KPIPeriod, pk=pk)
        if not can_calculate_kpi(request.user):
            raise PermissionDenied(_('You do not have permission to calculate KPI metrics.'))
        res = calculate_kpi_period(request.user, period, request=request)
        messages.success(
            request,
            _('Automated KPI evaluation completed for %(count)d employees.')
            % {'count': res['total_evaluated']},
        )
        return redirect('kpi:period_detail', pk=period.pk)


class KPIPeriodHRVerifyView(LoginRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(KPIPeriod, pk=pk)
        notes = request.POST.get('notes', '')
        hr_verify_kpi_period(request.user, period, notes=notes, request=request)
        messages.success(request, _('KPI period verified and submitted for Rector approval.'))
        return redirect('kpi:period_detail', pk=period.pk)


class KPIPeriodSubmitRectorView(LoginRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(KPIPeriod, pk=pk)
        submit_kpi_period_for_rector(request.user, period, request=request)
        messages.success(request, _('KPI period submitted to Rector.'))
        return redirect('kpi:period_detail', pk=period.pk)


class KPIPeriodRectorReviewView(LoginRequiredMixin, DetailView):
    model = KPIPeriod
    template_name = 'kpi/rector_review.html'
    context_object_name = 'period'

    def dispatch(self, request, *args, **kwargs):
        if not can_rector_approve_kpi(request.user):
            raise PermissionDenied(_('Only the Rector or Superadmin can access executive KPI review.'))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.object
        context['university_summary'] = calculate_university_kpi_summary(period)
        context['can_sign'] = can_rector_sign_kpi(self.request.user)
        return context


class KPIPeriodRectorApproveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(KPIPeriod, pk=pk)
        notes = request.POST.get('notes', '')
        rector_approve_kpi_period(request.user, period, notes=notes, request=request)
        messages.success(request, _('KPI period approved by Rector. Ready for electronic signature.'))
        return redirect('kpi:period_detail', pk=period.pk)


class KPIPeriodRectorRejectView(LoginRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(KPIPeriod, pk=pk)
        reason = request.POST.get('reason', '')
        try:
            rector_reject_kpi_period(request.user, period, reason=reason, request=request)
            messages.warning(request, _('KPI period returned for revision with feedback.'))
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect('kpi:period_detail', pk=period.pk)


class KPIPeriodRectorSignView(LoginRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(KPIPeriod, pk=pk)
        try:
            signature = rector_sign_kpi_period(request.user, period, request=request)
            messages.success(
                request,
                _('KPI period officially electronically signed by Rector (Verification ID: %(id)s).')
                % {'id': signature.verification_id},
            )
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, str(e))
        return redirect('kpi:period_detail', pk=period.pk)


class KPIPeriodCloseView(LoginRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(KPIPeriod, pk=pk)
        close_kpi_period(request.user, period, request=request)
        messages.success(request, _('KPI period %(code)s has been closed.') % {'code': period.code})
        return redirect('kpi:period_list')


class KPIAssignmentListView(LoginRequiredMixin, ListView):
    model = KPIAssignment
    template_name = 'kpi/assignment_list.html'
    context_object_name = 'assignments'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = (
            KPIAssignment.objects.select_related('kpi', 'kpi__category', 'user', 'period', 'result')
            .filter(is_active=True)
        )

        if user.is_superuser or user.is_rector or user.is_hr:
            pass
        elif user.is_vice_rector:
            scoped_depts = user.get_scoped_departments()
            qs = qs.filter(user__department__in=scoped_depts)
        elif user.is_department_head and user.department:
            qs = qs.filter(user__department=user.department)
        else:
            qs = qs.filter(user=user)

        period_id = self.request.GET.get('period')
        if period_id:
            qs = qs.filter(period_id=period_id)

        user_id = self.request.GET.get('user')
        if user_id:
            qs = qs.filter(user_id=user_id)

        return qs.order_by('user__last_name', 'kpi__name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['periods'] = KPIPeriod.objects.filter(is_active=True).order_by('-start_date')
        context['can_manage'] = can_manage_kpi(self.request.user)
        return context


class KPIAssignmentCreateView(LoginRequiredMixin, KPIManageRequiredMixin, CreateView):
    model = KPIAssignment
    form_class = KPIAssignmentForm
    template_name = 'kpi/assignment_form.html'
    success_url = reverse_lazy('kpi:assignment_list')

    def form_valid(self, form):
        form.instance.assigned_by = self.request.user
        messages.success(self.request, _('KPI assigned to employee successfully.'))
        return super().form_valid(form)


class KPIEvaluationView(LoginRequiredMixin, ScopedKPIAssignmentAccessMixin, View):
    template_name = 'kpi/evaluation_form.html'

    def get(self, request, pk):
        assignment = self.get_assignment()
        result = getattr(assignment, 'result', None)
        initial = {'actual_value': result.actual_value, 'notes': result.notes} if result else {}
        form = KPIResultEvaluationForm(initial=initial)
        return render(
            request,
            self.template_name,
            {
                'assignment': assignment,
                'result': result,
                'form': form,
                'can_approve': can_approve_kpi(request.user),
            },
        )

    def post(self, request, pk):
        assignment = self.get_assignment()
        form = KPIResultEvaluationForm(request.POST)
        if form.is_valid():
            val = form.cleaned_data['actual_value']
            notes = form.cleaned_data['notes']
            try:
                result = record_kpi_result(request.user, assignment, val, notes=notes, request=request)
                if 'approve' in request.POST and can_approve_kpi(request.user):
                    approve_kpi_result(request.user, result, request=request)
                    messages.success(request, _('KPI score approved and finalized.'))
                else:
                    messages.success(request, _('KPI result recorded successfully.'))
                return redirect('kpi:assignment_list')
            except PermissionDenied as e:
                messages.error(request, str(e))

        return render(
            request,
            self.template_name,
            {
                'assignment': assignment,
                'form': form,
                'can_approve': can_approve_kpi(request.user),
            },
        )


class KPICorrectionRequestCreateView(LoginRequiredMixin, View):
    template_name = 'kpi/correction_form.html'

    def get(self, request, result_id):
        result = get_object_or_404(KPIResult, pk=result_id)
        if not can_request_kpi_correction(request.user, result):
            raise PermissionDenied(_('You cannot submit a correction for this KPI result.'))
        form = KPICorrectionRequestForm(initial={'requested_actual_value': result.actual_value})
        return render(request, self.template_name, {'result': result, 'form': form})

    def post(self, request, result_id):
        result = get_object_or_404(KPIResult, pk=result_id)
        if not can_request_kpi_correction(request.user, result):
            raise PermissionDenied(_('You cannot submit a correction for this KPI result.'))
        form = KPICorrectionRequestForm(request.POST)
        if form.is_valid():
            request_kpi_correction(
                requester=request.user,
                result=result,
                requested_actual_value=form.cleaned_data['requested_actual_value'],
                reason=form.cleaned_data['reason'],
                evidence=form.cleaned_data['evidence'],
                request=request,
            )
            messages.success(request, _('Correction request submitted for review.'))
            return redirect('kpi:dashboard')
        return render(request, self.template_name, {'result': result, 'form': form})


class KPICorrectionDecideView(LoginRequiredMixin, View):
    def post(self, request, pk):
        correction = get_object_or_404(KPICorrectionRequest, pk=pk)
        decision = request.POST.get('decision')
        reason = request.POST.get('reason', '')
        approved = decision == 'APPROVE'
        rector_decide_kpi_correction(request.user, correction, approved=approved, decision_reason=reason, request=request)
        messages.success(request, _('Correction request decided.'))
        return redirect('kpi:period_detail', pk=correction.result.assignment.period_id)
