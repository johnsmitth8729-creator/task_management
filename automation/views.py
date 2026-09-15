from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from automation.forms import (
    AutomationRuleForm,
    EscalationPolicyForm,
    RecurringTaskRuleForm,
    SLAPolicyForm,
)
from automation.models import (
    AutomationExecution,
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)
from automation.permissions import (
    AutomationAccessRequiredMixin,
    AutomationManagementRequiredMixin,
    can_manage_recurring_tasks,
)
from automation.selectors import (
    get_automation_metrics,
    get_scoped_recurring_tasks,
)
from automation.services import (
    run_full_automation_cycle,
    toggle_automation_rule,
)


class AutomationDashboardView(LoginRequiredMixin, AutomationAccessRequiredMixin, TemplateView):
    template_name = 'automation/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['metrics'] = get_automation_metrics(self.request.user)
        context['recent_executions'] = AutomationExecution.objects.select_related('rule')[:15]
        context['active_rules'] = AutomationRule.objects.filter(is_active=True).order_by('priority_order')[:10]
        context['recurring_tasks'] = get_scoped_recurring_tasks(self.request.user)[:10]
        context['sla_policies'] = SLAPolicy.objects.all()
        context['escalation_policies'] = EscalationPolicy.objects.all()
        return context


# ---------------------------------------------------------------------------
# Rule Management
# ---------------------------------------------------------------------------

class RuleListView(LoginRequiredMixin, AutomationAccessRequiredMixin, ListView):
    model = AutomationRule
    template_name = 'automation/rule_list.html'
    context_object_name = 'rules'
    ordering = ['priority_order', 'name']


class RuleCreateView(LoginRequiredMixin, AutomationManagementRequiredMixin, CreateView):
    model = AutomationRule
    form_class = AutomationRuleForm
    template_name = 'automation/rule_form.html'
    success_url = reverse_lazy('automation:rule_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, _("Automation rule created successfully."))
        return super().form_valid(form)


class RuleUpdateView(LoginRequiredMixin, AutomationManagementRequiredMixin, UpdateView):
    model = AutomationRule
    form_class = AutomationRuleForm
    template_name = 'automation/rule_form.html'
    success_url = reverse_lazy('automation:rule_list')

    def form_valid(self, form):
        messages.success(self.request, _("Automation rule updated successfully."))
        return super().form_valid(form)


class RuleToggleView(LoginRequiredMixin, AutomationManagementRequiredMixin, View):
    def post(self, request, pk):
        rule = get_object_or_404(AutomationRule, pk=pk)
        new_state = toggle_automation_rule(request.user, rule)
        state_str = _("activated") if new_state else _("deactivated")
        messages.info(request, _(f"Rule '{rule.name}' was {state_str}."))
        return redirect('automation:rule_list')


# ---------------------------------------------------------------------------
# SLA Policies
# ---------------------------------------------------------------------------

class SLAPolicyListView(LoginRequiredMixin, AutomationAccessRequiredMixin, ListView):
    model = SLAPolicy
    template_name = 'automation/sla_list.html'
    context_object_name = 'policies'
    ordering = ['priority']


class SLAPolicyCreateView(LoginRequiredMixin, AutomationManagementRequiredMixin, CreateView):
    model = SLAPolicy
    form_class = SLAPolicyForm
    template_name = 'automation/sla_form.html'
    success_url = reverse_lazy('automation:sla_list')

    def form_valid(self, form):
        messages.success(self.request, _("SLA policy created successfully."))
        return super().form_valid(form)


class SLAPolicyUpdateView(LoginRequiredMixin, AutomationManagementRequiredMixin, UpdateView):
    model = SLAPolicy
    form_class = SLAPolicyForm
    template_name = 'automation/sla_form.html'
    success_url = reverse_lazy('automation:sla_list')

    def form_valid(self, form):
        messages.success(self.request, _("SLA policy updated successfully."))
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Escalation Policies
# ---------------------------------------------------------------------------

class EscalationPolicyListView(LoginRequiredMixin, AutomationAccessRequiredMixin, ListView):
    model = EscalationPolicy
    template_name = 'automation/escalation_list.html'
    context_object_name = 'policies'
    ordering = ['trigger_type', 'hours_threshold']


class EscalationPolicyCreateView(LoginRequiredMixin, AutomationManagementRequiredMixin, CreateView):
    model = EscalationPolicy
    form_class = EscalationPolicyForm
    template_name = 'automation/escalation_form.html'
    success_url = reverse_lazy('automation:escalation_list')

    def form_valid(self, form):
        messages.success(self.request, _("Escalation policy created successfully."))
        return super().form_valid(form)


class EscalationPolicyUpdateView(LoginRequiredMixin, AutomationManagementRequiredMixin, UpdateView):
    model = EscalationPolicy
    form_class = EscalationPolicyForm
    template_name = 'automation/escalation_form.html'
    success_url = reverse_lazy('automation:escalation_list')

    def form_valid(self, form):
        messages.success(self.request, _("Escalation policy updated successfully."))
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Recurring Tasks
# ---------------------------------------------------------------------------

class RecurringTaskListView(LoginRequiredMixin, AutomationAccessRequiredMixin, ListView):
    template_name = 'automation/recurring_list.html'
    context_object_name = 'tasks'

    def get_queryset(self):
        return get_scoped_recurring_tasks(self.request.user)


class RecurringTaskCreateView(LoginRequiredMixin, AutomationAccessRequiredMixin, CreateView):
    model = RecurringTaskRule
    form_class = RecurringTaskRuleForm
    template_name = 'automation/recurring_form.html'
    success_url = reverse_lazy('automation:recurring_list')

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_recurring_tasks(request.user):
            messages.error(request, _("Only Rector or Superadmin can configure recurring tasks."))
            return redirect('automation:recurring_list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, _("Recurring task rule configured successfully."))
        return super().form_valid(form)


class RecurringTaskUpdateView(LoginRequiredMixin, AutomationAccessRequiredMixin, UpdateView):
    model = RecurringTaskRule
    form_class = RecurringTaskRuleForm
    template_name = 'automation/recurring_form.html'
    success_url = reverse_lazy('automation:recurring_list')

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_recurring_tasks(request.user):
            messages.error(request, _("Only Rector or Superadmin can edit recurring tasks."))
            return redirect('automation:recurring_list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, _("Recurring task rule updated."))
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Execution History & Manual Scheduler Runner
# ---------------------------------------------------------------------------

class ExecutionHistoryView(LoginRequiredMixin, AutomationAccessRequiredMixin, ListView):
    model = AutomationExecution
    template_name = 'automation/execution_history.html'
    context_object_name = 'executions'
    paginate_by = 50

    def get_queryset(self):
        qs = AutomationExecution.objects.select_related('rule')
        q = self.request.GET.get('q')
        status = self.request.GET.get('status')
        if q:
            qs = qs.filter(Q(target_repr__icontains=q) | Q(result_summary__icontains=q) | Q(trigger_event__icontains=q))
        if status:
            qs = qs.filter(status=status)
        return qs


class RunAutomationCycleNowView(LoginRequiredMixin, AutomationManagementRequiredMixin, View):
    def post(self, request):
        results = run_full_automation_cycle()
        messages.success(
            request,
            _(f"Automation cycle completed: {results['tasks_generated']} recurring tasks created, "
              f"{results['sla_alerts_triggered']} SLA warnings triggered, "
              f"{results['escalations_dispatched']} escalations dispatched.")
        )
        return redirect('automation:dashboard')
