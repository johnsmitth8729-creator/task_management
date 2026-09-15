from django.core.management.base import BaseCommand
from automation.models import (
    AutomationExecution,
    AutomationRule,
    EscalationPolicy,
    RecurringTaskRule,
    SLAPolicy,
)
from tasks.models import Task


class Command(BaseCommand):
    help = 'Validates Workflow Automation, SLA configurations, and recurring task schedule integrity.'

    def handle(self, *args, **options):
        self.stdout.write("Starting Automation Subsystem Health Check...")
        issues = 0

        # 1. Check SLA Policy coverage across all priorities
        for priority in [Task.Priority.CRITICAL, Task.Priority.HIGH, Task.Priority.MEDIUM, Task.Priority.LOW]:
            policy = SLAPolicy.objects.filter(priority=priority, is_active=True).first()
            if not policy:
                self.stdout.write(self.style.WARNING(f"[WARNING] Missing active SLA policy for priority: {priority}"))
                issues += 1
            else:
                self.stdout.write(self.style.SUCCESS(f"[OK] SLA Policy for {priority}: {policy.resolution_hours}h"))

        # 2. Check RecurringTaskRules for valid foreign keys
        recurring_rules = RecurringTaskRule.objects.all()
        for rule in recurring_rules:
            if not rule.responsible_department_id:
                self.stdout.write(self.style.ERROR(f"[ERROR] Recurring task '{rule.title}' has no department."))
                issues += 1

        self.stdout.write(self.style.SUCCESS(f"[OK] {recurring_rules.count()} recurring task rule(s) verified."))

        # 3. Check AutomationRules
        active_rules = AutomationRule.objects.filter(is_active=True)
        self.stdout.write(self.style.SUCCESS(f"[OK] {active_rules.count()} active event-driven automation rule(s) configured."))

        # 4. Check Failed Executions
        failed_count = AutomationExecution.objects.filter(status=AutomationExecution.Status.FAILED).count()
        if failed_count > 0:
            self.stdout.write(self.style.WARNING(f"[WARNING] Detected {failed_count} failed automation execution(s) in history."))
        else:
            self.stdout.write(self.style.SUCCESS("[OK] Zero failed automation executions."))

        if issues == 0:
            self.stdout.write(self.style.SUCCESS("[SUCCESS] Automation Subsystem Health Check PASSED with 0 critical issues."))
        else:
            self.stdout.write(self.style.WARNING(f"[COMPLETED] Health Check finished with {issues} issue(s)."))
