import hashlib
import mimetypes
import os
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

MIME_TYPE_MAPPING = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'csv': 'text/csv',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'txt': 'text/plain',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'webp': 'image/webp',
    'gif': 'image/gif',
    'mp4': 'video/mp4',
    'webm': 'video/webm',
    'zip': 'application/zip',
    'rar': 'application/vnd.rar',
}


def sanitize_filename(filename: str) -> str:
    """
    Strips path traversal sequences, null bytes, and dangerous characters.
    Preserves a clean, readable basename.
    """
    if not filename:
        return f"file_{uuid.uuid4().hex[:8]}"

    # Strip null bytes and normalize path separators
    cleaned = filename.replace('\x00', '').replace('\\', '/')
    cleaned = os.path.basename(cleaned)

    # Split name and extension
    stem, ext = os.path.splitext(cleaned)
    ext = ext.lower().lstrip('.')

    # Remove path traversal tokens and dangerous characters from stem
    stem = stem.replace('..', '')
    safe_stem = re.sub(r'[^\w\s\-]', '', stem).strip().replace(' ', '_')
    if not safe_stem:
        safe_stem = f"file_{uuid.uuid4().hex[:8]}"

    return f"{safe_stem}.{ext}" if ext else safe_stem



def get_file_extension(filename: str) -> str:
    """Returns normalized lowercase extension without leading dot."""
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext


def validate_file_extension(filename: str) -> str:
    """
    Validates that the file extension is allowed and does not contain dangerous double extensions.
    Returns normalized extension.
    """
    if not filename:
        raise ValidationError(_('Filename cannot be empty.'))

    # Check for null bytes or path separators
    if '\x00' in filename or '/' in filename or '\\' in filename:
        raise ValidationError(_('Invalid characters in filename.'))

    parts = filename.lower().split('.')
    if len(parts) < 2:
        raise ValidationError(_('Files must have a valid extension (e.g. .pdf, .docx).'))

    ext = parts[-1]

    # Check blacklist first (including secondary extensions like file.exe.pdf)
    disallowed = getattr(settings, 'DISALLOWED_FILE_EXTENSIONS', [])
    for part in parts[1:]:
        if part in disallowed:
            raise ValidationError(
                _('File extension "{ext}" or embedded executable format is forbidden for security.').format(ext=part)
            )

    allowed = getattr(settings, 'ALLOWED_FILE_EXTENSIONS', [])
    if ext not in allowed:
        raise ValidationError(
            _('File extension ".{ext}" is not supported. Allowed formats: {allowed}').format(
                ext=ext,
                allowed=', '.join(sorted(allowed)),
            )
        )

    return ext


def validate_file_size(file_obj, is_video: bool = False) -> int:
    """
    Validates that file is not empty and does not exceed configured limits.
    Returns file size in bytes.
    """
    if not file_obj:
        raise ValidationError(_('No file provided.'))

    size = file_obj.size
    if size <= 0:
        raise ValidationError(_('The uploaded file is empty (0 bytes).'))

    max_mb = (
        getattr(settings, 'MAX_VIDEO_SIZE_MB', 200)
        if is_video
        else getattr(settings, 'MAX_FILE_SIZE_MB', 50)
    )
    max_bytes = max_mb * 1024 * 1024

    if size > max_bytes:
        raise ValidationError(
            _('File size ({size_mb:.1f} MB) exceeds maximum limit of {max_mb} MB.').format(
                size_mb=size / (1024 * 1024),
                max_mb=max_mb,
            )
        )

    return size


def calculate_file_checksum(file_obj) -> str:
    """Calculates SHA-256 checksum of an uploaded file."""
    sha256 = hashlib.sha256()
    try:
        if hasattr(file_obj, 'chunks'):
            for chunk in file_obj.chunks():
                sha256.update(chunk)
        else:
            current_pos = file_obj.tell() if hasattr(file_obj, 'tell') else 0
            file_obj.seek(0)
            while chunk := file_obj.read(65536):
                sha256.update(chunk)
            file_obj.seek(current_pos)
    except Exception:
        pass
    finally:
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
    return sha256.hexdigest()


def detect_content_type(filename: str, fallback: str = 'application/octet-stream') -> str:
    """Determines MIME content type based on extension with reliable defaults."""
    ext = get_file_extension(filename)
    if ext in MIME_TYPE_MAPPING:
        return MIME_TYPE_MAPPING[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback


def task_file_upload_to(instance, filename: str) -> str:
    """
    Generates secure, randomized, collision-resistant storage path.
    Format: task_files/<task_id>/<YYYY>/<MM>/<uuid>.<ext>
    """
    ext = get_file_extension(filename)
    unique_name = f"{uuid.uuid4().hex}"
    if ext:
        unique_name = f"{unique_name}.{ext}"

    now = timezone.now()
    task_id = str(instance.task_id) if instance.task_id else 'unassigned'
    return f"task_files/{task_id}/{now.year:04d}/{now.month:02d}/{unique_name}"
