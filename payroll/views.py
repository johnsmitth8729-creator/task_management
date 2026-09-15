from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from accounts.models import User
from core.models import AuditLog
from organization.models import Department, Position
from payroll.exports import generate_payslip_pdf, generate_period_payroll_excel
from payroll.forms import (
    CompensationComponentForm,
    KPIPayrollRuleForm,
    MarkPaidForm,
    PayrollAdjustmentForm,
    PayrollPeriodForm,
    PayrollTaxRuleForm,
    SalaryProfileForm,
)
from payroll.models import (
    CompensationComponent,
    KPIPayrollRule,
    PayrollAdjustment,
    PayrollLine,
    PayrollPeriod,
    PayrollRecord,
    PayrollTaxRule,
    SalaryBand,
    SalaryHistory,
    SalaryProfile,
)
from payroll.permissions import (
    PayrollAccessRequiredMixin,
    PayrollApproveRequiredMixin,
    PayrollManageRequiredMixin,
    SalaryManageRequiredMixin,
    ScopedPayrollRecordAccessMixin,
    can_approve_payroll,
    can_create_adjustment,
    can_manage_payroll,
    can_manage_salary,
    can_mark_paid,
    can_view_payroll,
    can_view_payroll_record,
    can_view_payroll_reports,
    can_view_user_salary,
    get_payroll_permission,
)
from payroll.services import (
    approve_period_payroll,
    approve_payroll_record,
    calculate_period_payroll,
    calculate_payroll,
    close_payroll_period,
    create_salary_profile,
    mark_payroll_paid,
)


# ---------------------------------------------------------------------------
# 1. Role-Based Dashboard
# ---------------------------------------------------------------------------

class PayrollDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'payroll/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        period_id = self.request.GET.get('period')

        if period_id:
            period = get_object_or_404(PayrollPeriod, pk=period_id)
        else:
            period = (
                PayrollPeriod.objects
                .filter(status__in=[PayrollPeriod.Status.OPEN, PayrollPeriod.Status.CALCULATING, PayrollPeriod.Status.PENDING_APPROVAL])
                .first() or
                PayrollPeriod.objects.order_by('-start_date').first()
            )

        context['current_period'] = period
        context['all_periods'] = PayrollPeriod.objects.all().order_by('-start_date')[:12]
        context['can_manage_salary'] = can_manage_salary(user)
        context['can_manage_payroll'] = can_manage_payroll(user)
        context['can_approve_payroll'] = can_approve_payroll(user)
        context['can_mark_paid'] = can_mark_paid(user)
        context['can_view_reports'] = can_view_payroll_reports(user)

        # 1. Employee Self-Service Dashboard
        if not can_view_payroll(user):
            context['view_type'] = 'EMPLOYEE'
            active_profile = SalaryProfile.objects.filter(user=user, status=SalaryProfile.Status.ACTIVE).first()
            context['active_profile'] = active_profile
            recent_payslips = (
                PayrollRecord.objects
                .filter(employee=user, status__in=[PayrollRecord.Status.APPROVED, PayrollRecord.Status.PAID])
                .select_related('period')
                .order_by('-period__start_date')[:6]
            )
            context['recent_payslips'] = recent_payslips
            latest = recent_payslips.first()
            context['latest_record'] = latest
            return context

        # Determine viewer role and scope records queryset accordingly
        records_qs = PayrollRecord.objects.all()
        if period:
            records_qs = records_qs.filter(period=period)

        # Finance / HR / Superadmin: full operational access — can see individual records
        can_see_individuals = (
            user.is_superuser
            or (user.is_finance and get_payroll_permission(user, 'can_view_payroll'))
            or (user.is_hr and not user.is_employee)
        )

        if can_see_individuals:
            context['view_type'] = 'UNIVERSITY'
        elif user.is_rector:
            # Rector sees ONLY university-wide aggregate metrics, NO individual records
            context['view_type'] = 'RECTOR'
        elif user.is_vice_rector:
            # Vice Rector sees ONLY aggregate metrics for assigned departments, NO individual records
            context['view_type'] = 'VICE_RECTOR'
            scoped_depts = user.get_scoped_departments()
            records_qs = records_qs.filter(employee__department__in=scoped_depts)
            context['scoped_departments'] = scoped_depts
        elif user.is_department_head and user.department:
            # Department Head sees ONLY aggregate metrics for own dept, NO individual records
            context['view_type'] = 'DEPARTMENT'
            records_qs = records_qs.filter(employee__department=user.department)
            context['department'] = user.department
        else:
            context['view_type'] = 'EMPLOYEE'
            return context

        # Aggregated Financial Metrics (safe for all leadership roles)
        agg = records_qs.aggregate(
            total_gross=Sum('gross_salary'),
            total_net=Sum('net_salary'),
            total_tax=Sum('tax_total'),
            total_deductions=Sum('total_deductions'),
            total_kpi=Sum('kpi_bonus'),
            avg_salary=Avg('gross_salary'),
            total_employees=Count('id'),
        )

        context['metrics'] = {
            'total_gross': agg['total_gross'] or Decimal('0.00'),
            'total_net': agg['total_net'] or Decimal('0.00'),
            'total_tax': agg['total_tax'] or Decimal('0.00'),
            'total_deductions': agg['total_deductions'] or Decimal('0.00'),
            'total_kpi': agg['total_kpi'] or Decimal('0.00'),
            'avg_salary': agg['avg_salary'] or Decimal('0.00'),
            'total_employees': agg['total_employees'] or 0,
        }

        # Status distribution
        context['status_counts'] = {
            'draft': records_qs.filter(status=PayrollRecord.Status.DRAFT).count(),
            'calculated': records_qs.filter(status=PayrollRecord.Status.CALCULATED).count(),
            'approved': records_qs.filter(status=PayrollRecord.Status.APPROVED).count(),
            'paid': records_qs.filter(status=PayrollRecord.Status.PAID).count(),
        }

        # Recent individual records: ONLY for Finance / HR / Superadmin
        # Rector, Vice Rector, Department Head MUST NOT receive individual salary records
        if can_see_individuals:
            context['recent_records'] = records_qs.select_related(
                'period', 'employee', 'employee__department'
            )[:8]
        else:
            # Leadership gets NO individual records in context (privacy)
            context['recent_records'] = PayrollRecord.objects.none()

        # Department Comparison (aggregate totals only, safe for leadership)
        if context['view_type'] in ['UNIVERSITY', 'RECTOR', 'VICE_RECTOR']:
            dept_stats = (
                records_qs.values('department_snapshot')
                .annotate(
                    headcount=Count('id'),
                    gross_sum=Sum('gross_salary'),
                    net_sum=Sum('net_salary'),
                    kpi_sum=Sum('kpi_bonus'),
                )
                .order_by('-gross_sum')
            )
            context['dept_stats'] = dept_stats

        return context


# ---------------------------------------------------------------------------
# 2. Employee Compensation & Salary Management
# ---------------------------------------------------------------------------

class EmployeeCompensationListView(SalaryManageRequiredMixin, ListView):
    """
    Employee compensation list — restricted to Superadmin, Finance, and authorized HR.
    Rector, Vice Rector, Department Head, and Employees do NOT have access to this view.
    (They only see aggregated metrics on their dashboard, not individual salary lists.)
    """
    model = User
    template_name = 'payroll/employees/list.html'
    context_object_name = 'employees'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = (
            User.objects
            .filter(is_active=True)
            .select_related('department', 'position', 'grade')
            .prefetch_related('salary_profiles')
            .order_by('first_name', 'last_name')
        )

        # Filters
        dept_id = self.request.GET.get('department')
        if dept_id:
            qs = qs.filter(department_id=dept_id)

        status_val = self.request.GET.get('status')
        if status_val:
            qs = qs.filter(employment_status=status_val)

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(username__icontains=q) |
                Q(email__icontains=q)
            )

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['departments'] = Department.objects.filter(is_active=True)
        context['can_manage_salary'] = can_manage_salary(self.request.user)
        return context


class EmployeeCompensationDetailView(LoginRequiredMixin, DetailView):
    model = User
    template_name = 'payroll/employees/detail.html'
    context_object_name = 'target_user'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        target_user = self.get_object()
        if not can_view_user_salary(request.user, target_user):
            raise PermissionDenied(_('You do not have permission to inspect this employee’s salary profile.'))
        # Audit log: SALARY_VIEWED when an authorized user views another employee's salary
        if request.user.id != target_user.id:
            AuditLog.objects.create(
                actor=request.user,
                action=AuditLog.Actions.SALARY_VIEWED,
                target_repr=f"User:{target_user.username}",
                details={"viewed_by": request.user.username, "target_user": target_user.username},
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        target = self.object
        context['active_profile'] = SalaryProfile.objects.filter(user=target, status=SalaryProfile.Status.ACTIVE).first()
        context['salary_histories'] = SalaryHistory.objects.filter(user=target).order_by('-created_at')
        context['past_payrolls'] = (
            PayrollRecord.objects
            .filter(employee=target)
            .select_related('period')
            .order_by('-period__start_date')[:12]
        )
        context['adjustments'] = PayrollAdjustment.objects.filter(employee=target).order_by('-created_at')[:10]
        context['can_manage_salary'] = can_manage_salary(self.request.user)
        context['can_create_adjustment'] = can_create_adjustment(self.request.user)
        return context


class SalaryProfileCreateView(SalaryManageRequiredMixin, CreateView):
    model = SalaryProfile
    form_class = SalaryProfileForm
    template_name = 'payroll/compensation/salary_form.html'

    def get_target_user(self):
        user_id = self.kwargs.get('user_id')
        return get_object_or_404(User, pk=user_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['target_user'] = self.get_target_user()
        context['current_profile'] = SalaryProfile.objects.filter(user=context['target_user'], status=SalaryProfile.Status.ACTIVE).first()
        return context

    def form_valid(self, form):
        target_user = self.get_target_user()
        data = form.cleaned_data
        create_salary_profile(
            actor=self.request.user,
            user=target_user,
            base_salary=data['base_salary'],
            effective_from=data['effective_from'],
            currency=data.get('currency', 'UZS'),
            salary_type=data.get('salary_type', SalaryProfile.SalaryType.MONTHLY),
            notes=data.get('notes', ''),
            request=self.request,
        )
        messages.success(
            self.request,
            _('Base salary for %(user)s updated successfully.') % {'user': target_user.display_name}
        )
        return redirect('payroll:employee_detail', pk=target_user.pk)


# ---------------------------------------------------------------------------
# 3. Payroll Periods & Engine Execution
# ---------------------------------------------------------------------------

class PayrollPeriodListView(PayrollAccessRequiredMixin, ListView):
    model = PayrollPeriod
    template_name = 'payroll/periods/list.html'
    context_object_name = 'periods'
    paginate_by = 15

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_manage_payroll'] = can_manage_payroll(self.request.user)
        return context


class PayrollPeriodCreateView(PayrollManageRequiredMixin, CreateView):
    model = PayrollPeriod
    form_class = PayrollPeriodForm
    template_name = 'payroll/periods/form.html'
    success_url = reverse_lazy('payroll:period_list')

    def form_valid(self, form):
        period = form.save(commit=False)
        period.created_by = self.request.user
        period.status = PayrollPeriod.Status.OPEN
        period.save()
        messages.success(self.request, _('Payroll period "%(name)s" created and opened.') % {'name': period.name})
        return redirect(self.success_url)


class PayrollPeriodDetailView(PayrollAccessRequiredMixin, DetailView):
    model = PayrollPeriod
    template_name = 'payroll/periods/detail.html'
    context_object_name = 'period'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.object
        records = period.records.select_related('employee', 'employee__department').all()

        user = self.request.user
        if user.is_vice_rector:
            records = records.filter(employee__department__in=user.get_scoped_departments())
        elif user.is_department_head and user.department:
            records = records.filter(employee__department=user.department)

        context['records'] = records
        context['record_count'] = records.count()
        context['can_manage_payroll'] = can_manage_payroll(user)
        context['can_approve_payroll'] = can_approve_payroll(user)
        context['can_mark_paid'] = can_mark_paid(user)
        return context


class PayrollCalculatePeriodView(PayrollManageRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(PayrollPeriod, pk=pk)
        try:
            count = calculate_period_payroll(period, actor=request.user, request=request)
            messages.success(
                request,
                _('Successfully calculated payroll for %(count)d employees in period %(name)s.') % {
                    'count': count,
                    'name': period.name,
                }
            )
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('payroll:period_detail', pk=period.pk)


class PayrollCalculateSingleView(PayrollManageRequiredMixin, View):
    def post(self, request, user_id, period_id):
        employee = get_object_or_404(User, pk=user_id)
        period = get_object_or_404(PayrollPeriod, pk=period_id)
        try:
            record = calculate_payroll(employee, period, actor=request.user, request=request)
            messages.success(
                request,
                _('Payroll calculated for %(user)s: Net %(net)s %(currency)s.') % {
                    'user': employee.display_name,
                    'net': f"{record.net_salary:,.2f}",
                    'currency': record.currency,
                }
            )
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('payroll:period_detail', pk=period.pk)


# ---------------------------------------------------------------------------
# 4. Payroll Records, Approval & Disbursement
# ---------------------------------------------------------------------------

class PayrollRecordListView(LoginRequiredMixin, ListView):
    model = PayrollRecord
    template_name = 'payroll/payroll/list.html'
    context_object_name = 'records'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = (
            PayrollRecord.objects
            .select_related('period', 'employee', 'employee__department')
            .order_by('-period__start_date', 'employee_name_snapshot')
        )

        # STRICT PRIVACY: Rector, Vice Rector, Department Head, and ordinary Employees
        # may ONLY view their OWN payroll records — no peeking at other employees' records.
        can_see_all = (
            user.is_superuser
            or (user.is_finance and get_payroll_permission(user, 'can_view_payroll'))
            or (user.is_hr and not user.is_employee)
        )
        if not can_see_all:
            qs = qs.filter(employee=user)

        # Filters (applied after scope)
        period_id = self.request.GET.get('period')
        if period_id:
            qs = qs.filter(period_id=period_id)

        dept_id = self.request.GET.get('department')
        if dept_id and can_see_all:
            qs = qs.filter(employee__department_id=dept_id)

        status_val = self.request.GET.get('status')
        if status_val:
            qs = qs.filter(status=status_val)

        payment_val = self.request.GET.get('payment_status')
        if payment_val:
            qs = qs.filter(payment_status=payment_val)

        q = self.request.GET.get('q', '').strip()
        if q and can_see_all:
            qs = qs.filter(
                Q(employee_name_snapshot__icontains=q) |
                Q(employee_username_snapshot__icontains=q)
            )

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['periods'] = PayrollPeriod.objects.all().order_by('-start_date')
        context['departments'] = Department.objects.filter(is_active=True)
        context['can_approve_payroll'] = can_approve_payroll(self.request.user)
        context['can_mark_paid'] = can_mark_paid(self.request.user)
        return context


class PayrollRecordDetailView(ScopedPayrollRecordAccessMixin, DetailView):
    model = PayrollRecord
    template_name = 'payroll/payroll/detail.html'
    context_object_name = 'record'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        record = self.object
        context['lines'] = record.lines.all().order_by('component_type', 'name_snapshot')
        context['can_approve'] = can_approve_payroll(self.request.user) and record.status == PayrollRecord.Status.CALCULATED
        context['can_mark_paid'] = can_mark_paid(self.request.user) and record.status == PayrollRecord.Status.APPROVED
        context['mark_paid_form'] = MarkPaidForm()
        return context


class PayrollRecordApproveView(PayrollApproveRequiredMixin, View):
    def post(self, request, pk):
        record = get_object_or_404(PayrollRecord, pk=pk)
        approve_payroll_record(request.user, record, request=request)
        messages.success(
            request,
            _('Payroll for %(user)s approved and locked.') % {'user': record.employee_name_snapshot}
        )
        return redirect('payroll:record_detail', pk=record.pk)


class PayrollPeriodApproveAllView(PayrollApproveRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(PayrollPeriod, pk=pk)
        count = approve_period_payroll(request.user, period, request=request)
        messages.success(
            request,
            _('Successfully approved and locked %(count)d payroll records for period %(name)s.') % {
                'count': count,
                'name': period.name,
            }
        )
        return redirect('payroll:period_detail', pk=period.pk)


class PayrollRecordMarkPaidView(PayrollManageRequiredMixin, View):
    def post(self, request, pk):
        record = get_object_or_404(PayrollRecord, pk=pk)
        if not can_mark_paid(request.user):
            raise PermissionDenied(_('You do not have permission to mark payroll as paid.'))
        form = MarkPaidForm(request.POST)
        ref = form.cleaned_data['payment_reference'] if form.is_valid() else ''
        try:
            mark_payroll_paid(request.user, record, payment_reference=ref, request=request)
            messages.success(
                request,
                _('Payroll for %(user)s successfully marked as PAID.') % {'user': record.employee_name_snapshot}
            )
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('payroll:record_detail', pk=record.pk)


class PayrollPeriodCloseView(PayrollApproveRequiredMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(PayrollPeriod, pk=pk)
        close_payroll_period(request.user, period, request=request)
        messages.success(request, _('Payroll period "%(name)s" successfully closed.') % {'name': period.name})
        return redirect('payroll:period_detail', pk=period.pk)


# ---------------------------------------------------------------------------
# 5. Manual Adjustments
# ---------------------------------------------------------------------------

class PayrollAdjustmentCreateView(LoginRequiredMixin, CreateView):
    model = PayrollAdjustment
    form_class = PayrollAdjustmentForm
    template_name = 'payroll/compensation/adjustment_form.html'
    success_url = reverse_lazy('payroll:dashboard')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_create_adjustment(request.user):
            raise PermissionDenied(_('You do not have permission to create payroll adjustments.'))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        adj = form.save(commit=False)
        adj.created_by = self.request.user
        # Auto-approve if user is Superadmin or Rector
        if self.request.user.is_superuser or self.request.user.is_rector:
            adj.status = PayrollAdjustment.Status.APPROVED
            adj.approved_by = self.request.user
            adj.approved_at = timezone.now()
        adj.save()
        messages.success(self.request, _('Payroll adjustment submitted successfully.'))
        return redirect('payroll:employee_detail', pk=adj.employee.pk)


# ---------------------------------------------------------------------------
# 6. Employee Self-Service: Payslips
# ---------------------------------------------------------------------------

class EmployeeMyPayslipsView(LoginRequiredMixin, ListView):
    model = PayrollRecord
    template_name = 'payroll/payslips/my_payslips.html'
    context_object_name = 'payslips'
    paginate_by = 12

    def get_queryset(self):
        return (
            PayrollRecord.objects
            .filter(employee=self.request.user, status__in=[PayrollRecord.Status.APPROVED, PayrollRecord.Status.PAID])
            .select_related('period')
            .order_by('-period__start_date')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_profile'] = SalaryProfile.objects.filter(user=self.request.user, status=SalaryProfile.Status.ACTIVE).first()
        return context


class EmployeePayslipDetailView(LoginRequiredMixin, DetailView):
    model = PayrollRecord
    template_name = 'payroll/payslips/payslip_detail.html'
    context_object_name = 'record'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        record = self.get_object()
        if not can_view_payroll_record(request.user, record):
            raise PermissionDenied(_('You do not have authorization to inspect this payslip.'))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['lines'] = self.object.lines.all().order_by('component_type', 'name_snapshot')
        return context


# ---------------------------------------------------------------------------
# 7. Document Exports (PDF & Excel)
# ---------------------------------------------------------------------------

class PayslipExportPDFView(LoginRequiredMixin, View):
    def get(self, request, pk):
        record = get_object_or_404(PayrollRecord, pk=pk)
        if not can_view_payroll_record(request.user, record):
            raise PermissionDenied(_('You are not authorized to download this payslip.'))
        return generate_payslip_pdf(record)


class PeriodExportExcelView(PayrollAccessRequiredMixin, View):
    def get(self, request, pk):
        period = get_object_or_404(PayrollPeriod, pk=pk)
        if not can_view_payroll_reports(request.user):
            raise PermissionDenied(_('You do not have permission to export payroll reports.'))

        records_qs = period.records.select_related('employee', 'employee__department').all()
        user = request.user
        if user.is_vice_rector:
            records_qs = records_qs.filter(employee__department__in=user.get_scoped_departments())
        elif user.is_department_head and user.department:
            records_qs = records_qs.filter(employee__department=user.department)

        return generate_period_payroll_excel(period, records_qs)


# ---------------------------------------------------------------------------
# 8. Compensation Rules Management
# ---------------------------------------------------------------------------

class CompensationComponentListView(PayrollManageRequiredMixin, ListView):
    model = CompensationComponent
    template_name = 'payroll/compensation/component_list.html'
    context_object_name = 'components'


class CompensationComponentCreateView(PayrollManageRequiredMixin, CreateView):
    model = CompensationComponent
    form_class = CompensationComponentForm
    template_name = 'payroll/compensation/component_form.html'
    success_url = reverse_lazy('payroll:component_list')


class PayrollTaxRuleListView(PayrollManageRequiredMixin, ListView):
    model = PayrollTaxRule
    template_name = 'payroll/compensation/tax_rule_list.html'
    context_object_name = 'tax_rules'


class PayrollTaxRuleCreateView(PayrollManageRequiredMixin, CreateView):
    model = PayrollTaxRule
    form_class = PayrollTaxRuleForm
    template_name = 'payroll/compensation/tax_rule_form.html'
    success_url = reverse_lazy('payroll:tax_rule_list')


class KPIPayrollRuleListView(PayrollManageRequiredMixin, ListView):
    model = KPIPayrollRule
    template_name = 'payroll/compensation/kpi_rule_list.html'
    context_object_name = 'kpi_rules'


class KPIPayrollRuleCreateView(PayrollManageRequiredMixin, CreateView):
    model = KPIPayrollRule
    form_class = KPIPayrollRuleForm
    template_name = 'payroll/compensation/kpi_rule_form.html'
    success_url = reverse_lazy('payroll:kpi_rule_list')


class PayrollReportsSummaryView(PayrollAccessRequiredMixin, TemplateView):
    template_name = 'payroll/reports/summary.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not can_view_payroll_reports(self.request.user):
            raise PermissionDenied(_('You do not have access to payroll reports.'))

        periods = PayrollPeriod.objects.all().order_by('-start_date')[:12]
        records = PayrollRecord.objects.filter(status__in=[PayrollRecord.Status.APPROVED, PayrollRecord.Status.PAID])

        user = self.request.user
        if user.is_vice_rector:
            records = records.filter(employee__department__in=user.get_scoped_departments())
        elif user.is_department_head and user.department:
            records = records.filter(employee__department=user.department)

        context['periods'] = periods
        context['records'] = records[:50]
        context['total_disbursed'] = records.aggregate(Sum('net_salary'))['net_salary__sum'] or Decimal('0.00')
        context['total_kpi_bonuses'] = records.aggregate(Sum('kpi_bonus'))['kpi_bonus__sum'] or Decimal('0.00')
        return context


class PayslipExportPDFView(ScopedPayrollRecordAccessMixin, View):
    """Download payslip as a PDF file."""

    def get(self, request, pk, *args, **kwargs):
        record = get_object_or_404(PayrollRecord, pk=pk)
        if not can_view_payroll_record(request.user, record):
            raise PermissionDenied(_('You do not have access to this payslip.'))
        pdf_bytes = generate_payslip_pdf(record)
        filename = f"Payslip_{record.employee_username_snapshot}_{record.period.code}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response


class PeriodExportExcelView(PayrollManageRequiredMixin, View):
    """
    Download period payroll summary as an Excel file.
    RESTRICTED: Superadmin, Finance (can_view_payroll_reports), authorized HR only.
    Rector, Vice Rector, Department Head, and Employees are DENIED (403).
    """

    def get(self, request, pk, *args, **kwargs):
        user = request.user
        # Explicit deny for leadership roles who may pass PayrollManageRequiredMixin via can_view_payroll
        if not (
            user.is_superuser
            or (user.is_finance and get_payroll_permission(user, 'can_view_payroll_reports'))
            or (user.is_hr and not user.is_employee)
        ):
            raise PermissionDenied(_('You do not have permission to export payroll data.'))
        period = get_object_or_404(PayrollPeriod, pk=pk)
        records_qs = PayrollRecord.objects.filter(period=period).select_related(
            'employee', 'period', 'approved_by'
        )
        excel_bytes = generate_period_payroll_excel(period, records_qs)
        filename = f"Payroll_{period.code}.xlsx"
        response = HttpResponse(
            excel_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class EmployeeMySalaryView(LoginRequiredMixin, TemplateView):
    """
    Employee self-service: view own salary profile, payslips, and salary history.
    Available to ALL authenticated users (every employee sees only their own data).
    """
    template_name = 'payroll/my_salary.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['active_profile'] = SalaryProfile.objects.filter(
            user=user, status=SalaryProfile.Status.ACTIVE
        ).first()
        context['salary_histories'] = SalaryHistory.objects.filter(
            user=user
        ).order_by('-created_at')[:12]
        context['payslips'] = (
            PayrollRecord.objects
            .filter(employee=user, status__in=[PayrollRecord.Status.APPROVED, PayrollRecord.Status.PAID])
            .select_related('period')
            .order_by('-period__start_date')[:12]
        )
        context['adjustments'] = PayrollAdjustment.objects.filter(
            employee=user
        ).order_by('-created_at')[:10]
        return context
