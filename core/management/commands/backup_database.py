import hashlib
import json
import os
from datetime import datetime
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create an enterprise-grade JSON database backup with integrity checksum and metadata manifest.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default=os.path.join(settings.BASE_DIR, 'backups'),
            help='Directory path where backups are stored.',
        )
        parser.add_argument(
            '--tag',
            type=str,
            default='',
            help='Optional tag label for the backup (e.g. pre_migration, daily).',
        )
        parser.add_argument(
            '--exclude-sessions',
            action='store_true',
            default=True,
            help='Exclude ephemeral sessions and contenttypes from backup.',
        )

    def handle(self, *args, **options):
        output_dir = options['output_dir']
        tag = options.get('tag', '').strip()
        os.makedirs(output_dir, exist_ok=True)

        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        tag_suffix = f"_{tag}" if tag else ""
        backup_filename = f"backup_{timestamp_str}{tag_suffix}.json"
        meta_filename = f"backup_{timestamp_str}{tag_suffix}_meta.json"

        backup_filepath = os.path.join(output_dir, backup_filename)
        meta_filepath = os.path.join(output_dir, meta_filename)

        self.stdout.write(self.style.NOTICE(f"Starting database backup to {backup_filepath}..."))

        excludes = ['contenttypes', 'auth.Permission']
        if options['exclude_sessions']:
            excludes.append('sessions.Session')

        # Execute dumpdata
        try:
            with open(backup_filepath, 'w', encoding='utf-8') as f:
                call_command(
                    'dumpdata',
                    natural_foreign=True,
                    natural_primary=True,
                    exclude=excludes,
                    indent=2,
                    stdout=f,
                )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Backup dump failed: {e}"))
            if os.path.exists(backup_filepath):
                os.remove(backup_filepath)
            raise

        # Calculate SHA256
        hasher = hashlib.sha256()
        with open(backup_filepath, 'rb') as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        checksum = hasher.hexdigest()
        file_size = os.path.getsize(backup_filepath)

        # Create metadata manifest
        manifest = {
            'timestamp': datetime.now().isoformat(),
            'backup_filename': backup_filename,
            'tag': tag or 'standard',
            'sha256_checksum': checksum,
            'file_size_bytes': file_size,
            'file_size_human': f"{file_size / (1024 * 1024):.2f} MB" if file_size >= 1048576 else f"{file_size / 1024:.2f} KB",
            'db_engine': settings.DATABASES['default']['ENGINE'],
            'excluded_models': excludes,
        }

        with open(meta_filepath, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"[OK] Backup successfully completed: {backup_filename}"))
        self.stdout.write(f"  * Size: {manifest['file_size_human']}")
        self.stdout.write(f"  * SHA256: {checksum}")
        self.stdout.write(f"  * Manifest: {meta_filename}")
