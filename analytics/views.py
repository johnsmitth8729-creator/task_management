import json
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from accounts.models import User
from analytics.charts import (
    get_deadline_compliance_chart_data,
    get_department_comparison_chart_data,
    get_signature_trends_chart_data,
    get_task_status_chart_data,
    get_task_trends_chart_data,
)
from analytics.exports import (
    generate_analytics_csv,
    generate_analytics_excel,
    generate_analytics_pdf,
)
from analytics.models import AnalyticsThresholdConfig, SavedReportConfiguration
from analytics.permissions import (
    can_export_analytics_report,
    can_view_audit_analytics,
    can_view_department_analytics,
    can_view_executive_analytics,
    can_view_hr_analytics,
    can_view_payroll_analytics,
    can_view_personal_analytics,
    can_view_signature_analytics,
)
from analytics.selectors import (
    get_audit_security_metrics,
    get_bottleneck_metrics,
    get_deadline_metrics,
    get_department_comparison_data,
    get_employee_personal_metrics,
    get_executive_metrics,
    get_hr_analytics_metrics,
    get_payroll_analytics_metrics,
    get_scoped_departments_for_user,
    get_signature_metrics,
    parse_date_range,
)
from analytics.services import (
    get_executive_alerts,
    record_analytics_view_event,
    record_report_export_event,
)
from organization.models import Department


class AnalyticsIndexRedirectView(LoginRequiredMixin, View):
    """
    Entrypoint redirecting /analytics/ to the canonical /analytics/executive/ route.
    Preserves any query parameters passed to the root entrypoint.
    """
    def get(self, request, *args, **kwargs):
        query_string = request.META.get('QUERY_STRING', '')
        url = reverse('analytics:executive_dashboard')
        if query_string:
            url = f"{url}?{query_string}"
        return redirect(url)


class ExecutiveAnalyticsView(LoginRequiredMixin, TemplateView):
    """
    Primary analytics hub for Rector, Vice Rector, Department Heads, and Superadmin.
    Automatically redirects regular employees to personal analytics.
    """
    template_name = 'analytics/executive_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Regular employees go directly to personal dashboard
        if request.user.is_employee and not (
            request.user.is_rector or request.user.is_vice_rector or
            request.user.is_department_head or request.user.is_superuser or
            request.user.is_hr or request.user.is_finance
        ):
            return redirect('analytics:personal_analytics')

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Parse date range filter
        period = self.request.GET.get('period', '30d')
        start_str = self.request.GET.get('start_date')
        end_str = self.request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)
        date_range = (start_dt, end_dt)

        # Department filter (with backend validation)
        dept_id = self.request.GET.get('department_id')
        selected_dept = None
        if dept_id:
            try:
                selected_dept = Department.objects.get(id=dept_id, is_active=True)
                if not can_view_department_analytics(user, selected_dept):
                    selected_dept = None
                    dept_id = None
            except (Department.DoesNotExist, ValueError):
                dept_id = None

        # Gather metrics
        metrics = get_executive_metrics(user, department_id=dept_id, date_range=date_range)
        bottlenecks = get_bottleneck_metrics(user, department_id=dept_id, date_range=date_range)
        deadlines = get_deadline_metrics(user, department_id=dept_id, date_range=date_range)
        dept_comparison = get_department_comparison_data(user, date_range=date_range)
        threshold_config = AnalyticsThresholdConfig.get_active()
        alerts = get_executive_alerts(metrics, bottlenecks, threshold_config)

        # Chart JSON configurations
        status_chart = get_task_status_chart_data(user, department_id=dept_id, date_range=date_range)
        trends_chart = get_task_trends_chart_data(user, department_id=dept_id, date_range=date_range)
        dept_chart = get_department_comparison_chart_data(user, date_range=date_range)
        deadline_chart = get_deadline_compliance_chart_data(user, department_id=dept_id, date_range=date_range)

        # Available departments for filter
        visible_depts = get_scoped_departments_for_user(user)

        context.update({
            'period': period,
            'period_label': period_label,
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'selected_department': selected_dept,
            'visible_departments': visible_depts,
            'metrics': metrics,
            'bottlenecks': bottlenecks,
            'deadlines': deadlines,
            'dept_comparison': dept_comparison,
            'alerts': alerts,
            'status_chart_json': json.dumps(status_chart),
            'trends_chart_json': json.dumps(trends_chart),
            'dept_chart_json': json.dumps(dept_chart),
            'deadline_chart_json': json.dumps(deadline_chart),
            'can_view_hr': can_view_hr_analytics(user),
            'can_view_payroll': can_view_payroll_analytics(user),
            'can_view_signatures': can_view_signature_analytics(user),
            'can_view_audit': can_view_audit_analytics(user),
        })

        # Record audit log
        record_analytics_view_event(user, 'EXECUTIVE', self.request.META.get('REMOTE_ADDR'), self.request.META.get('HTTP_USER_AGENT'))
        return context


class DepartmentAnalyticsView(LoginRequiredMixin, TemplateView):
    """Department Head and scoped leadership view."""
    template_name = 'analytics/department_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        period = self.request.GET.get('period', '30d')
        start_str = self.request.GET.get('start_date')
        end_str = self.request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)
        date_range = (start_dt, end_dt)

        dept_id = self.request.GET.get('department_id')
        selected_dept = None

        if dept_id:
            try:
                selected_dept = Department.objects.get(id=dept_id, is_active=True)
                if not can_view_department_analytics(user, selected_dept):
                    raise PermissionDenied(_("You are not authorized to view this department's analytics."))
            except (Department.DoesNotExist, ValueError):
                raise Http404(_("Department not found."))
        elif user.is_department_head and user.department:
            selected_dept = user.department
        elif user.is_vice_rector:
            selected_dept = get_scoped_departments_for_user(user).first()
        elif user.is_superuser or user.is_rector:
            selected_dept = Department.objects.filter(is_active=True).first()

        if not selected_dept:
            raise PermissionDenied(_("No department assigned or authorized."))

        dept_id_str = str(selected_dept.id)
        metrics = get_executive_metrics(user, department_id=dept_id_str, date_range=date_range)
        bottlenecks = get_bottleneck_metrics(user, department_id=dept_id_str, date_range=date_range)
        deadlines = get_deadline_metrics(user, department_id=dept_id_str, date_range=date_range)

        # Department employee performance table (NO salary!)
        employees = selected_dept.users.filter(is_active=True).select_related('position')
        emp_stats = []
        for emp in employees:
            m = get_employee_personal_metrics(emp, date_range=date_range)
            emp_stats.append({
                'employee': emp,
                'total_assigned': m['total_assigned'],
                'completed': m['completed'],
                'in_progress': m['in_progress'],
                'overdue': m['overdue'],
                'ontime_rate': m['ontime_rate'],
                'kpi_score': m['my_kpi_score'],
            })

        status_chart = get_task_status_chart_data(user, department_id=dept_id_str, date_range=date_range)
        trends_chart = get_task_trends_chart_data(user, department_id=dept_id_str, date_range=date_range)

        context.update({
            'department': selected_dept,
            'visible_departments': get_scoped_departments_for_user(user),
            'period': period,
            'period_label': period_label,
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'metrics': metrics,
            'bottlenecks': bottlenecks,
            'deadlines': deadlines,
            'employee_stats': emp_stats,
            'status_chart_json': json.dumps(status_chart),
            'trends_chart_json': json.dumps(trends_chart),
        })

        record_analytics_view_event(user, 'DEPARTMENT', self.request.META.get('REMOTE_ADDR'), self.request.META.get('HTTP_USER_AGENT'))
        return context


class EmployeePersonalAnalyticsView(LoginRequiredMixin, TemplateView):
    """Personal performance, task completion pace, and KPI analytics for individual staff."""
    template_name = 'analytics/personal_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Support authorized managers viewing a specific subordinate
        target_user = user
        emp_id = self.request.GET.get('employee_id')
        if emp_id:
            try:
                candidate = User.objects.get(id=emp_id)
                if can_view_personal_analytics(user, candidate):
                    target_user = candidate
                else:
                    raise PermissionDenied(_("You are not authorized to view this employee's analytics."))
            except (User.DoesNotExist, ValueError):
                pass

        period = self.request.GET.get('period', '30d')
        start_str = self.request.GET.get('start_date')
        end_str = self.request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)
        date_range = (start_dt, end_dt)

        metrics = get_employee_personal_metrics(target_user, date_range=date_range)

        context.update({
            'target_user': target_user,
            'is_self': target_user.id == user.id,
            'period': period,
            'period_label': period_label,
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'metrics': metrics,
        })

        record_analytics_view_event(user, 'PERSONAL', self.request.META.get('REMOTE_ADDR'), self.request.META.get('HTTP_USER_AGENT'))
        return context


class HRAnalyticsView(LoginRequiredMixin, TemplateView):
    """Staffing, organizational distributions, and workforce health for HR Managers and Rector."""
    template_name = 'analytics/hr_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not can_view_hr_analytics(request.user):
            raise PermissionDenied(_("You do not have permission to view HR analytics."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        period = self.request.GET.get('period', '30d')
        start_str = self.request.GET.get('start_date')
        end_str = self.request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)

        hr_metrics = get_hr_analytics_metrics(user, date_range=(start_dt, end_dt))

        context.update({
            'period': period,
            'period_label': period_label,
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'hr_metrics': hr_metrics,
        })

        record_analytics_view_event(user, 'HR', self.request.META.get('REMOTE_ADDR'), self.request.META.get('HTTP_USER_AGENT'))
        return context


class PayrollAnalyticsView(LoginRequiredMixin, TemplateView):
    """Macro payroll and institutional compensation analytics for Finance and Superadmin."""
    template_name = 'analytics/payroll_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not can_view_payroll_analytics(request.user):
            raise PermissionDenied(_("You do not have permission to view Payroll analytics."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        period = self.request.GET.get('period', '30d')
        start_str = self.request.GET.get('start_date')
        end_str = self.request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)

        dept_id = self.request.GET.get('department_id')
        payroll_metrics = get_payroll_analytics_metrics(user, department_id=dept_id, date_range=(start_dt, end_dt))

        context.update({
            'period': period,
            'period_label': period_label,
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'payroll_metrics': payroll_metrics,
            'visible_departments': Department.objects.filter(is_active=True),
        })

        record_analytics_view_event(user, 'PAYROLL', self.request.META.get('REMOTE_ADDR'), self.request.META.get('HTTP_USER_AGENT'))
        return context


class SignatureAnalyticsView(LoginRequiredMixin, TemplateView):
    """Cryptographic signature throughput and verification audit metrics."""
    template_name = 'analytics/signature_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not can_view_signature_analytics(request.user):
            raise PermissionDenied(_("You do not have permission to view Electronic Signature analytics."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        period = self.request.GET.get('period', '30d')
        start_str = self.request.GET.get('start_date')
        end_str = self.request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)
        date_range = (start_dt, end_dt)

        sig_metrics = get_signature_metrics(user, date_range=date_range)
        sig_trends = get_signature_trends_chart_data(user, date_range=date_range)

        context.update({
            'period': period,
            'period_label': period_label,
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'sig_metrics': sig_metrics,
            'sig_trends_json': json.dumps(sig_trends),
        })

        record_analytics_view_event(user, 'SIGNATURE', self.request.META.get('REMOTE_ADDR'), self.request.META.get('HTTP_USER_AGENT'))
        return context


class AuditSecurityAnalyticsView(LoginRequiredMixin, TemplateView):
    """Superadmin-only security audit analytics."""
    template_name = 'analytics/audit_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not can_view_audit_analytics(request.user):
            raise PermissionDenied(_("Only Superadmin can view security audit analytics."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        period = self.request.GET.get('period', '30d')
        start_str = self.request.GET.get('start_date')
        end_str = self.request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)

        audit_metrics = get_audit_security_metrics(user, date_range=(start_dt, end_dt))

        context.update({
            'period': period,
            'period_label': period_label,
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'audit_metrics': audit_metrics,
        })

        record_analytics_view_event(user, 'AUDIT', self.request.META.get('REMOTE_ADDR'), self.request.META.get('HTTP_USER_AGENT'))
        return context


class ReportCenterView(LoginRequiredMixin, TemplateView):
    """Unified reporting portal for generating and scheduling reports."""
    template_name = 'analytics/report_center.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        context.update({
            'visible_departments': get_scoped_departments_for_user(user),
            'can_view_hr': can_view_hr_analytics(user),
            'can_view_payroll': can_view_payroll_analytics(user),
            'can_view_signatures': can_view_signature_analytics(user),
            'can_view_audit': can_view_audit_analytics(user),
            'report_types': SavedReportConfiguration.ReportTypes.choices,
        })
        return context


class ReportExportView(LoginRequiredMixin, View):
    """
    Export generator streaming authorized reports in PDF, Excel, or CSV format.
    Strictly verifies permissions before generation.
    """
    def get(self, request, *args, **kwargs):
        user = request.user
        report_type = request.GET.get('report_type')
        export_format = request.GET.get('format', 'pdf').lower()
        dept_id = request.GET.get('department_id')

        if not can_export_analytics_report(user, report_type, dept_id):
            raise PermissionDenied(_("You are not authorized to export this report."))

        period = request.GET.get('period', '30d')
        start_str = request.GET.get('start_date')
        end_str = request.GET.get('end_date')
        start_dt, end_dt, period_label = parse_date_range(period, start_str, end_str)
        date_range = (start_dt, end_dt)

        rt = SavedReportConfiguration.ReportTypes
        summary = {}
        headers = []
        rows = []
        report_title = _("Analytics Report")
        subtitle = f"{_('Period')}: {period_label}"

        # 1. University Tasks Report
        if report_type == rt.UNIVERSITY_TASKS:
            report_title = _("University Task Overview Report")
            metrics = get_executive_metrics(user, department_id=dept_id, date_range=date_range)
            summary = {
                _('Total Tasks'): metrics['total_tasks'],
                _('Completed Tasks'): metrics['completed_tasks'],
                _('Completion Rate'): f"{metrics['completion_rate']}%",
                _('On-Time Rate'): f"{metrics['ontime_rate']}%",
                _('Overdue Tasks'): metrics['overdue_tasks'],
                _('Signed Tasks'): metrics['signed_tasks'],
            }
            headers = [_('Task #'), _('Title'), _('Department'), _('Status'), _('Priority'), _('Deadline')]
            from analytics.selectors import get_scoped_tasks
            for t in get_scoped_tasks(user, department_id=dept_id, date_range=date_range)[:300]:
                rows.append([
                    t.task_number,
                    t.title[:40],
                    t.responsible_department.name if t.responsible_department else '-',
                    t.get_status_display(),
                    t.get_priority_display(),
                    t.deadline.strftime('%Y-%m-%d') if t.deadline else '-',
                ])

        # 2. Department Performance Report
        elif report_type == rt.DEPARTMENT_PERFORMANCE:
            report_title = _("Department Performance Report")
            dept_data = get_department_comparison_data(user, date_range=date_range)
            headers = [
                _('Department'), _('Staff'), _('Total Tasks'), _('Completed'),
                _('Active'), _('Overdue'), _('Completion Rate'), _('On-Time Rate'), _('Avg Days')
            ]
            for d in dept_data:
                rows.append([
                    d['department_name'],
                    str(d['employee_count']),
                    str(d['total_tasks']),
                    str(d['completed']),
                    str(d['active']),
                    str(d['overdue']),
                    f"{d['completion_rate']}%",
                    f"{d['ontime_rate']}%",
                    f"{d['avg_completion_days']} d",
                ])

        # 3. Payroll Analytics Report (Finance/Superadmin only)
        elif report_type == rt.PAYROLL_ANALYTICS:
            report_title = _("Payroll & Compensation Analytics Report")
            p_metrics = get_payroll_analytics_metrics(user, department_id=dept_id, date_range=date_range)
            summary = {
                _('Total Gross Payroll'): f"{p_metrics.get('total_gross', 0):,.2f} UZS",
                _('Total Net Payroll'): f"{p_metrics.get('total_net', 0):,.2f} UZS",
                _('Total KPI Bonuses'): f"{p_metrics.get('total_kpi', 0):,.2f} UZS",
                _('Total Taxes'): f"{p_metrics.get('total_tax', 0):,.2f} UZS",
                _('Total Records'): p_metrics.get('record_count', 0),
            }
            headers = [_('Department'), _('Gross Spend (UZS)')]
            for ds in p_metrics.get('department_spend', []):
                rows.append([ds['name'], f"{ds['total']:,.2f}"])

        # 4. Signature Audit Report
        elif report_type == rt.SIGNATURE_AUDIT:
            report_title = _("Electronic Signature & Verification Audit Report")
            s_metrics = get_signature_metrics(user, date_range=date_range)
            summary = {
                _('Total Signed'): s_metrics.get('total_signed', 0),
                _('Pending Signature'): s_metrics.get('pending_signature', 0),
                _('Signature Rate'): f"{s_metrics.get('signature_rate', 0)}%",
                _('Revoked Signatures'): s_metrics.get('revoked_count', 0),
                _('Total Verifications'): s_metrics.get('total_verifications', 0),
            }
            headers = [_('Verification ID'), _('Task'), _('Signer'), _('Signed At'), _('Status')]
            from signatures.models import ElectronicSignature
            for sig in ElectronicSignature.objects.all().select_related('task', 'signer')[:300]:
                rows.append([
                    sig.verification_id,
                    sig.task.task_number if sig.task else '-',
                    sig.signer.get_full_name() if sig.signer else '-',
                    sig.signed_at.strftime('%Y-%m-%d %H:%M') if sig.signed_at else '-',
                    _('Revoked') if sig.status == 'REVOKED' else _('Valid'),
                ])

        # 5. Deadline Compliance Report
        elif report_type == rt.DEADLINE_COMPLIANCE:
            report_title = _("Deadline Compliance & Bottleneck Report")
            dl = get_deadline_metrics(user, department_id=dept_id, date_range=date_range)
            summary = {
                _('Compliance Rate'): f"{dl.get('deadline_compliance_rate', 0)}%",
                _('Due Today'): dl.get('due_today', 0),
                _('Due This Week'): dl.get('due_this_week', 0),
                _('Currently Overdue'): dl.get('overdue', 0),
            }
            headers = [_('Metric'), _('Count')]
            rows = [
                [_('Completed Before Deadline'), str(dl.get('completed_before_deadline', 0))],
                [_('Completed On Deadline'), str(dl.get('completed_on_deadline', 0))],
                [_('Completed After Deadline (Late)'), str(dl.get('completed_after_deadline', 0))],
                [_('Currently Overdue Active Tasks'), str(dl.get('overdue', 0))],
            ]

        # 6. Fallback HR Distribution
        else:
            report_title = _("Workforce Distribution Report")
            hr = get_hr_analytics_metrics(user, date_range=date_range)
            summary = {
                _('Total Employees'): hr.get('total_employees', 0),
                _('Active Employees'): hr.get('active_employees', 0),
                _('Average KPI Score'): f"{hr.get('average_kpi_score', 0)}%",
            }
            headers = [_('Department'), _('Active Headcount')]
            for d in hr.get('department_distribution', []):
                rows.append([d['name'], str(d['headcount'])])

        # Audit log export action
        record_report_export_event(user, report_type, export_format, request.META.get('REMOTE_ADDR'), request.META.get('HTTP_USER_AGENT'))

        # Return file response
        timestamp_slug = timezone.now().strftime('%Y%m%d_%H%M')
        if export_format == 'excel' or export_format == 'xlsx':
            buffer = generate_analytics_excel(report_title, summary, headers, rows)
            response = HttpResponse(
                buffer.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="analytics_report_{timestamp_slug}.xlsx"'
            return response

        elif export_format == 'csv':
            csv_data = generate_analytics_csv(headers, rows)
            response = HttpResponse(csv_data, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="analytics_report_{timestamp_slug}.csv"'
            return response

        else: # Default PDF
            pdf_buffer = generate_analytics_pdf(report_title, subtitle, summary, headers, rows, user.get_full_name() or user.username)
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="analytics_report_{timestamp_slug}.pdf"'
            return response


# ===========================================================================
# JSON API ENDPOINTS FOR DYNAMIC FRONTEND CHARTS
# ===========================================================================

def api_task_analytics(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    period = request.GET.get('period', '30d')
    start_dt, end_dt, _ = parse_date_range(period, request.GET.get('start_date'), request.GET.get('end_date'))
    dept_id = request.GET.get('department_id')

    metrics = get_executive_metrics(request.user, department_id=dept_id, date_range=(start_dt, end_dt))
    return JsonResponse(metrics)


def api_trend_analytics(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    period = request.GET.get('period', '30d')
    start_dt, end_dt, _ = parse_date_range(period, request.GET.get('start_date'), request.GET.get('end_date'))
    dept_id = request.GET.get('department_id')

    data = get_task_trends_chart_data(request.user, department_id=dept_id, date_range=(start_dt, end_dt))
    return JsonResponse(data)


def api_department_analytics(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    period = request.GET.get('period', '30d')
    start_dt, end_dt, _ = parse_date_range(period, request.GET.get('start_date'), request.GET.get('end_date'))

    data = get_department_comparison_data(request.user, date_range=(start_dt, end_dt))
    return JsonResponse({'departments': data})
