import time
from django.core.management.base import BaseCommand
from django.utils import timezone

from automation.services import run_full_automation_cycle


class Command(BaseCommand):
    help = 'Executes the University Workflow Automation & SLA Scheduler cycle.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run continuously as a background daemon loop checking every 60 seconds.',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Interval in seconds when running in daemon mode (default: 60s).',
        )

    def handle(self, *args, **options):
        is_daemon = options['daemon']
        interval = options['interval']

        if is_daemon:
            self.stdout.write(self.style.SUCCESS(f"Starting Automation Scheduler Daemon (interval: {interval}s)..."))
            try:
                while True:
                    res = run_full_automation_cycle()
                    self.stdout.write(
                        f"[{res['timestamp']}] Tasks Created: {res['tasks_generated']}, "
                        f"SLA Warnings: {res['sla_alerts_triggered']}, "
                        f"Escalations: {res['escalations_dispatched']}"
                    )
                    time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Automation Scheduler Daemon stopped by user."))
        else:
            self.stdout.write("Executing one-shot Automation & SLA Scheduler cycle...")
            res = run_full_automation_cycle()
            self.stdout.write(self.style.SUCCESS(
                f"[OK] Cycle complete: {res['tasks_generated']} tasks created, "
                f"{res['sla_alerts_triggered']} SLA warnings, "
                f"{res['escalations_dispatched']} escalations."
            ))
