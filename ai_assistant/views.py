from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView, ListView

from ai_assistant.engine import (
    AIAssistantEngine,
    ExecutiveReportGenerator,
    RiskDetectionEngine,
)
from ai_assistant.models import (
    AIConversation,
    AIMessage,
    ExecutiveBriefing,
    ManagementRiskIndicator,
)


class AIAssistantChatView(LoginRequiredMixin, View):
    template_name = 'ai_assistant/chat.html'

    def get(self, request, conv_id=None):
        user = request.user
        conversations = AIConversation.objects.filter(user=user).order_by('-updated_at')
        active_conversation = None
        messages_list = []

        if conv_id:
            active_conversation = get_object_or_404(AIConversation, id=conv_id, user=user)
            messages_list = active_conversation.messages.all().order_by('created_at')
        elif conversations.exists():
            active_conversation = conversations.first()
            messages_list = active_conversation.messages.all().order_by('created_at')

        return render(request, self.template_name, {
            'conversations': conversations,
            'active_conversation': active_conversation,
            'messages_list': messages_list,
        })

    def post(self, request, conv_id=None):
        prompt = request.POST.get('prompt', '').strip()
        if not prompt:
            return redirect('ai_assistant:chat')

        conv = None
        if conv_id:
            conv = get_object_or_404(AIConversation, id=conv_id, user=request.user)

        assistant_msg, conversation = AIAssistantEngine.ask(
            user=request.user,
            prompt=prompt,
            conversation=conv
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'OK',
                'conversation_id': str(conversation.id),
                'assistant_message': assistant_msg.content,
                'created_at': assistant_msg.created_at.strftime('%H:%M'),
            })

        return redirect('ai_assistant:chat_conversation', conv_id=conversation.id)


class ManagementRiskCenterView(LoginRequiredMixin, ListView):
    model = ManagementRiskIndicator
    template_name = 'ai_assistant/risk_center.html'
    context_object_name = 'risks'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = ManagementRiskIndicator.objects.filter(is_resolved=False).select_related('department').order_by('-severity', '-detected_at')
        severity = self.request.GET.get('severity')
        if severity:
            qs = qs.filter(severity=severity)
        if user.is_department_head and not (user.is_superuser or user.is_rector or user.is_vice_rector):
            qs = qs.filter(department=user.department)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['critical_count'] = ManagementRiskIndicator.objects.filter(is_resolved=False, severity=ManagementRiskIndicator.Severity.CRITICAL).count()
        context['high_count'] = ManagementRiskIndicator.objects.filter(is_resolved=False, severity=ManagementRiskIndicator.Severity.HIGH).count()
        context['total_unresolved'] = ManagementRiskIndicator.objects.filter(is_resolved=False).count()
        context['current_severity'] = self.request.GET.get('severity', '')
        context['can_manage_risks'] = self.request.user.is_superuser or self.request.user.is_rector or self.request.user.is_vice_rector or self.request.user.is_department_head
        return context


class RiskResolveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        risk = get_object_or_404(ManagementRiskIndicator, id=pk)
        risk.is_resolved = True
        risk.resolved_by = request.user
        risk.resolved_at = timezone.now()
        risk.save(update_fields=['is_resolved', 'resolved_by', 'resolved_at'])
        messages.success(request, _('Risk indicator marked as resolved.'))
        return redirect('ai_assistant:risk_center')


class RunRiskScanNowView(LoginRequiredMixin, View):
    def post(self, request):
        risks = RiskDetectionEngine.run_full_risk_assessment()
        messages.success(request, _('Full risk scan completed. %d potential risk indicators analyzed.') % len(risks))
        return redirect('ai_assistant:risk_center')


class ExecutiveBriefingListView(LoginRequiredMixin, ListView):
    model = ExecutiveBriefing
    template_name = 'ai_assistant/briefing_list.html'
    context_object_name = 'briefings'
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.is_rector:
            return ExecutiveBriefing.objects.all().select_related('generated_for').order_by('-created_at')
        return ExecutiveBriefing.objects.filter(generated_for=user).order_by('-created_at')


class ExecutiveBriefingDetailView(LoginRequiredMixin, DetailView):
    model = ExecutiveBriefing
    template_name = 'ai_assistant/briefing_detail.html'
    context_object_name = 'briefing'


class GenerateBriefingNowView(LoginRequiredMixin, View):
    def post(self, request):
        briefing = ExecutiveReportGenerator.generate_weekly_briefing(request.user)
        messages.success(request, _('Executive Briefing report successfully generated.'))
        return redirect('ai_assistant:briefing_detail', pk=briefing.id)
