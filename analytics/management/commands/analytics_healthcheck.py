from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils.translation import gettext as _

from analytics.models import AnalyticsThresholdConfig
from tasks.models import Task, TaskAssignment

try:
    from signatures.models import ElectronicSignature
except ImportError:
    ElectronicSignature = None


class Command(BaseCommand):
    help = _('Verifies data integrity, timestamp relationships, and relations for the analytics subsystem.')

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting Analytics Subsystem Health Check..."))
        issues_found = 0

        # 1. Check tasks with completed_at < created_at
        bad_timestamps = Task.objects.filter(
            status=Task.Status.COMPLETED,
            completed_at__isnull=False,
            created_at__isnull=False,
            completed_at__lt=F('created_at')
        )
        if bad_timestamps.exists():
            self.stdout.write(self.style.ERROR(f"Found {bad_timestamps.count()} completed tasks with completed_at before created_at."))
            issues_found += bad_timestamps.count()
        else:
            self.stdout.write(self.style.SUCCESS("[OK] Task timestamp ordering is consistent."))

        # 2. Check completed tasks missing completed_at
        missing_completed_at = Task.objects.filter(status=Task.Status.COMPLETED, completed_at__isnull=True)
        if missing_completed_at.exists():
            self.stdout.write(self.style.WARNING(f"Found {missing_completed_at.count()} completed tasks without completed_at."))
            issues_found += missing_completed_at.count()
        else:
            self.stdout.write(self.style.SUCCESS("[OK] Completed tasks have valid completion dates."))

        # 3. Check orphan assignments
        orphan_assignments = TaskAssignment.objects.filter(task__isnull=True)
        if orphan_assignments.exists():
            self.stdout.write(self.style.ERROR(f"Found {orphan_assignments.count()} orphan assignments."))
            issues_found += orphan_assignments.count()
        else:
            self.stdout.write(self.style.SUCCESS("[OK] Task assignments maintain valid foreign keys."))

        # 4. Check signature linkage
        if ElectronicSignature:
            orphan_sigs = ElectronicSignature.objects.filter(task__isnull=True)
            if orphan_sigs.exists():
                self.stdout.write(self.style.ERROR(f"Found {orphan_sigs.count()} signatures with missing tasks."))
                issues_found += orphan_sigs.count()
            else:
                self.stdout.write(self.style.SUCCESS("[OK] Electronic signatures cleanly linked to tasks."))

        # 5. Check threshold configuration
        cfg = AnalyticsThresholdConfig.get_active()
        self.stdout.write(self.style.SUCCESS(f"[OK] Active Threshold Configuration: '{cfg.name}' loaded successfully."))

        if issues_found == 0:
            self.stdout.write(self.style.SUCCESS("\n[SUCCESS] Analytics Subsystem Health Check PASSED with 0 issues."))
        else:
            self.stdout.write(self.style.WARNING(f"\n[WARNING] Analytics Subsystem Health Check completed with {issues_found} issue(s)."))
