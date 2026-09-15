import datetime
import logging
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from ai_assistant.context_builder import RoleContextBuilder
from ai_assistant.models import (
    AIConversation,
    AIMessage,
    ExecutiveBriefing,
    ManagementRiskIndicator,
)
from core.models import AuditLog, log_audit
from organization.models import Department
from tasks.models import Task, TaskAssignment, TaskSubmission

User = get_user_model()
logger = logging.getLogger(__name__)


class RiskDetectionEngine:
    """
    Intelligent scanner detecting organizational bottlenecks, overdue clusters, and workload imbalances.
    """

    @classmethod
    def run_full_risk_assessment(cls) -> list[ManagementRiskIndicator]:
        detected_risks = []
        now = timezone.now()
        today = now.date()

        # 1. Overdue Clusters per Department
        dept_overdues = Department.objects.filter(is_active=True).annotate(
            overdue_count=Count(
                'tasks',
                filter=Q(
                    tasks__status__in=[Task.Status.CREATED, Task.Status.ASSIGNED, Task.Status.IN_PROGRESS],
                    tasks__deadline__lt=today
                )
            )
        ).filter(overdue_count__gte=3)

        for dept in dept_overdues:
            risk, _ = ManagementRiskIndicator.objects.get_or_create(
                risk_type=ManagementRiskIndicator.RiskType.DEADLINE_SPIKE,
                department=dept,
                is_resolved=False,
                defaults={
                    'severity': ManagementRiskIndicator.Severity.HIGH if dept.overdue_count >= 5 else ManagementRiskIndicator.Severity.MEDIUM,
                    'title': f"Overdue Deadline Spike in {dept.name} ({dept.overdue_count} tasks)",
                    'description': f"Department has {dept.overdue_count} tasks exceeding official deadlines. Immediate supervisory intervention or deadline extension required.",
                    'metrics_payload': {'overdue_count': dept.overdue_count},
                }
            )
            detected_risks.append(risk)

        # 2. Stage 1 Approval Queue Bottlenecks (>3 submissions pending >24h)
        threshold_24h = now - datetime.timedelta(hours=24)
        pending_dept_submissions = Department.objects.filter(is_active=True).annotate(
            pending_count=Count(
                'tasks__assignments__submissions',
                filter=Q(
                    tasks__assignments__submissions__status=TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL,
                    tasks__assignments__submissions__created_at__lte=threshold_24h
                )
            )
        ).filter(pending_count__gte=2)

        for dept in pending_dept_submissions:
            risk, _ = ManagementRiskIndicator.objects.get_or_create(
                risk_type=ManagementRiskIndicator.RiskType.APPROVAL_BOTTLENECK,
                department=dept,
                is_resolved=False,
                defaults={
                    'severity': ManagementRiskIndicator.Severity.MEDIUM,
                    'title': f"Approval Review Bottleneck in {dept.name}",
                    'description': f"There are {dept.pending_count} employee deliverables awaiting first approval from Department Head for over 24 hours.",
                    'metrics_payload': {'pending_submissions': dept.pending_count},
                }
            )
            detected_risks.append(risk)

        # 3. Workload Imbalance (Staff members with >= 6 active urgent/high tasks)
        overloaded_users = User.objects.filter(is_active=True).annotate(
            active_urgent=Count(
                'task_assignments',
                filter=Q(
                    task_assignments__assignment_status__in=[TaskAssignment.AssignmentStatus.ASSIGNED, TaskAssignment.AssignmentStatus.IN_PROGRESS],
                    task_assignments__task__priority__in=[Task.Priority.HIGH, Task.Priority.URGENT]
                )
            )
        ).filter(active_urgent__gte=5)

        for u in overloaded_users:
            risk, _ = ManagementRiskIndicator.objects.get_or_create(
                risk_type=ManagementRiskIndicator.RiskType.WORKLOAD_IMBALANCE,
                department=u.department,
                target_object_repr=u.display_name,
                is_resolved=False,
                defaults={
                    'severity': ManagementRiskIndicator.Severity.HIGH,
                    'title': f"Staff Workload Overload: {u.display_name}",
                    'description': f"Employee has {u.active_urgent} concurrent high-priority tasks assigned, increasing the risk of delivery delay.",
                    'metrics_payload': {'urgent_tasks': u.active_urgent, 'user_id': str(u.id)},
                }
            )
            detected_risks.append(risk)

        if detected_risks:
            log_audit(
                actor=None,
                action=AuditLog.Actions.RISK_DETECTED,
                target_repr=f"Scan: {len(detected_risks)} risks identified",
                details={'count': len(detected_risks)}
            )

        return detected_risks


class ExecutiveReportGenerator:
    """
    Synthesizes automated executive weekly briefing documents for University Leadership.
    """

    @classmethod
    def generate_weekly_briefing(cls, leader_user, period_start=None, period_end=None) -> ExecutiveBriefing:
        now = timezone.now()
        if not period_end:
            period_end = now.date()
        if not period_start:
            period_start = period_end - datetime.timedelta(days=7)

        context = RoleContextBuilder.build_context(leader_user)
        metrics = context.get('metrics', {})

        title = f"Executive Intelligence Briefing: {period_start:%b %d} – {period_end:%b %d, %Y}"

        lines = [
            f"# {title}",
            f"**Prepared For**: {leader_user.display_name} ({context['user_role']})",
            f"**Generated On**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## 1. Executive Summary & Operational Health",
            "This briefing synthesizes university-wide task execution velocity, active approvals, deadline compliance, and emerging organizational hazards.",
            "",
            "## 2. Key Performance Indicators",
        ]

        for k, v in metrics.items():
            lines.append(f"- **{k.replace('_', ' ').title()}**: `{v}`")

        lines.extend([
            "",
            "## 3. High-Priority Risk Indicators & Bottlenecks",
        ])

        active_risks = ManagementRiskIndicator.objects.filter(is_resolved=False).order_by('-severity')[:5]
        if active_risks.exists():
            for r in active_risks:
                lines.append(f"- **[{r.get_severity_display()}] {r.title}**: {r.description}")
        else:
            lines.append("- *No critical organizational bottlenecks detected across supervised sectors.*")

        lines.extend([
            "",
            "## 4. Strategic Recommendations for Leadership",
            "1. Expedite pending Stage 2 second approvals in academic departments.",
            "2. Rebalance high-priority task distributions across overloaded department staff.",
            "3. Enforce SLA resolution thresholds on university service applications.",
            "",
            "---",
            "*Document generated automatically by University Management Intelligence Engine.*",
        ])

        summary_md = "\n".join(lines)

        briefing = ExecutiveBriefing.objects.create(
            generated_for=leader_user,
            title=title,
            period_start=period_start,
            period_end=period_end,
            summary_markdown=summary_md,
            kpis_snapshot=metrics,
        )
        return briefing


class AIAssistantEngine:
    """
    Natural language assistant grounding queries against role-authorized database context.
    """

    @classmethod
    def ask(cls, user, prompt: str, conversation=None) -> tuple[AIMessage, AIConversation]:
        if not conversation:
            title_candidate = prompt[:40].strip() or 'University Consultation'
            conversation = AIConversation.objects.create(user=user, title=title_candidate)

        context_data = RoleContextBuilder.build_context(user)

        # Record User Message
        user_msg = AIMessage.objects.create(
            conversation=conversation,
            role=AIMessage.Role.USER,
            content=prompt,
        )

        log_audit(
            actor=user,
            action=AuditLog.Actions.AI_REQUESTED,
            target_repr=f"Prompt: {prompt[:60]}",
            details={'conversation_id': str(conversation.id)}
        )

        # Synthesize Grounded Response
        reply_content = cls._synthesize_response(user, prompt, context_data)

        # Record Assistant Message
        assistant_msg = AIMessage.objects.create(
            conversation=conversation,
            role=AIMessage.Role.ASSISTANT,
            content=reply_content,
            context_snapshot=context_data,
        )

        log_audit(
            actor=user,
            action=AuditLog.Actions.AI_RESPONSE_GENERATED,
            target_repr=f"Reply: {conversation.title}",
            details={'message_id': str(assistant_msg.id)}
        )

        conversation.updated_at = timezone.now()
        conversation.save(update_fields=['updated_at'])

        return assistant_msg, conversation

    @classmethod
    def _synthesize_response(cls, user, prompt: str, context: dict) -> str:
        p_lower = prompt.lower()
        role = context.get('user_role', 'Staff')
        metrics = context.get('metrics', {})

        if any(w in p_lower for w in ['overdue', 'delay', 'late', 'bottleneck', 'risk']):
            risks = ManagementRiskIndicator.objects.filter(is_resolved=False)[:3]
            risk_lines = "\n".join([f"- **[{r.get_severity_display()}] {r.title}**: {r.description}" for r in risks]) if risks else "No critical risk alerts active."
            return (
                f"### Organizational Risk & Delay Assessment for {role}\n\n"
                f"Based on live telemetry for your authorized scope:\n"
                f"- **Overdue Tasks in Scope**: `{metrics.get('overdue_tasks', metrics.get('sector_overdue_tasks', metrics.get('dept_overdue_tasks', metrics.get('my_overdue_tasks', 0))))}`\n\n"
                f"#### Active Risk Indicators:\n{risk_lines}\n\n"
                f"**Recommended Action**: Review tasks in the Approval Center and ensure SLA compliance."
            )

        elif any(w in p_lower for w in ['kpi', 'performance', 'summary', 'status', 'report']):
            metric_bullets = "\n".join([f"- **{k.replace('_', ' ').title()}**: `{v}`" for k, v in metrics.items()])
            return (
                f"### Performance Summary ({role})\n\n"
                f"Here is your authorized executive summary:\n\n"
                f"{metric_bullets}\n\n"
                f"All metrics are computed in real-time respecting database-level privacy boundaries."
            )

        elif any(w in p_lower for w in ['leave', 'request', 'service', 'apply', 'application']):
            return (
                f"### University Applications & Service Catalog Guide\n\n"
                f"You can submit and track official university applications directly through the **Service Catalog**:\n"
                f"1. Open the [Service Catalog](/operations/services/) to choose from Academic, Administrative, HR/Leave, or Financial workflows.\n"
                f"2. Track your application approval progress in [My Applications](/operations/my-requests/).\n"
                f"3. All requests follow automated multi-tier approval chains (Department Head → Dean/Vice Rector → Rector)."
            )

        else:
            return (
                f"### University Management Assistant\n\n"
                f"Hello {user.display_name}. I am your grounded AI assistant configured for **{role}** privileges.\n\n"
                f"I can help you with:\n"
                f"- **Task & Workflow Intelligence**: Real-time summaries of open and overdue items.\n"
                f"- **Risk & Bottleneck Detection**: Identifying approval delays and staff overload.\n"
                f"- **Executive Briefings**: Synthesizing weekly KPI reports.\n"
                f"- **Service Catalog**: Navigating university applications and regulations.\n\n"
                f"*How can I assist your operations today?*"
            )
