import hashlib
import json
import os
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Restore the database from an enterprise JSON backup file with checksum verification.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='Path to the backup JSON file to restore.',
        )
        parser.add_argument(
            '--latest',
            action='store_true',
            help='Automatically restore the latest backup in the backups/ directory.',
        )
        parser.add_argument(
            '--skip-checksum',
            action='store_true',
            help='Skip SHA256 checksum verification against metadata manifest.',
        )
        parser.add_argument(
            '--noinput',
            action='store_true',
            help='Do not prompt for interactive confirmation before restoring.',
        )

    def handle(self, *args, **options):
        backup_file = options.get('file')
        latest = options.get('latest')
        skip_checksum = options.get('skip_checksum')
        noinput = options.get('noinput')

        if not backup_file and not latest:
            raise CommandError("Please specify either --file <path> or --latest.")

        if latest:
            backup_dir = os.path.join(settings.BASE_DIR, 'backups')
            if not os.path.exists(backup_dir):
                raise CommandError(f"Backup directory '{backup_dir}' does not exist.")
            json_files = [
                os.path.join(backup_dir, f)
                for f in os.listdir(backup_dir)
                if f.startswith('backup_') and f.endswith('.json') and not f.endswith('_meta.json')
            ]
            if not json_files:
                raise CommandError("No backup files found in backups directory.")
            backup_file = max(json_files, key=os.path.getctime)
            self.stdout.write(f"Selected latest backup file: {backup_file}")

        if not os.path.exists(backup_file):
            raise CommandError(f"Backup file '{backup_file}' does not exist.")

        # Manifest checksum verification
        meta_file = backup_file.replace('.json', '_meta.json')
        if os.path.exists(meta_file) and not skip_checksum:
            self.stdout.write("Verifying SHA256 checksum with manifest...")
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            expected_checksum = meta.get('sha256_checksum')
            if expected_checksum:
                hasher = hashlib.sha256()
                with open(backup_file, 'rb') as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
                actual_checksum = hasher.hexdigest()
                if actual_checksum != expected_checksum:
                    raise CommandError(
                        f"Checksum mismatch! Expected: {expected_checksum}, Actual: {actual_checksum}. Backup may be corrupted."
                    )
                self.stdout.write(self.style.SUCCESS("[OK] SHA256 Checksum verified."))

        if not noinput:
            confirm = input(
                f"WARNING: This will load data into the current database ({settings.DATABASES['default']['NAME']}).\n"
                "Type 'yes' to proceed: "
            )
            if confirm.strip().lower() != 'yes':
                self.stdout.write(self.style.WARNING("Database restore aborted by user."))
                return

        self.stdout.write(self.style.NOTICE(f"Restoring database from {backup_file}..."))
        try:
            call_command('loaddata', backup_file)
            self.stdout.write(self.style.SUCCESS("[OK] Database restoration completed successfully."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Restore failed: {e}"))
            raise
