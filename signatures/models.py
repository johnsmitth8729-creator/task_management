import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ElectronicSignature(models.Model):
    """
    Represents an official cryptographic electronic signing event for a final-approved task.
    Preserves cryptographic integrity, signer attribution, and verification metadata.
    """

    class SignatureType(models.TextChoices):
        RECTOR_SIGNATURE = 'RECTOR_SIGNATURE', _('Rector Electronic Signature')
        VICE_RECTOR_SIGNATURE = 'VICE_RECTOR_SIGNATURE', _('Vice Rector Electronic Signature')
        SUPERADMIN_SIGNATURE = 'SUPERADMIN_SIGNATURE', _('Superadmin Administrative Signature')
        KPI_PERIOD_SIGNATURE = 'KPI_PERIOD_SIGNATURE', _('Rector KPI Period Final Signature')
        OTHER_AUTHORIZED_SIGNATURE = 'OTHER_AUTHORIZED_SIGNATURE', _('Other Authorized Signature')

    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        SIGNED = 'SIGNED', _('Signed / Valid')
        REVOKED = 'REVOKED', _('Revoked')
        INVALID = 'INVALID', _('Invalid')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        'tasks.Task',
        verbose_name=_('task'),
        on_delete=models.PROTECT,
        related_name='signatures',
        null=True,
        blank=True,
    )
    kpi_period = models.ForeignKey(
        'kpi.KPIPeriod',
        verbose_name=_('KPI period'),
        on_delete=models.PROTECT,
        related_name='signatures',
        null=True,
        blank=True,
    )
    signer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('signer'),
        on_delete=models.PROTECT,
        related_name='electronic_signatures',
    )
    signature_type = models.CharField(
        _('signature type'),
        max_length=40,
        choices=SignatureType.choices,
        default=SignatureType.RECTOR_SIGNATURE,
        db_index=True,
    )
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=Status.choices,
        default=Status.SIGNED,
        db_index=True,
    )
    signed_at = models.DateTimeField(_('signed at'), default=timezone.now, db_index=True)
    verification_id = models.CharField(
        _('verification ID'),
        max_length=64,
        unique=True,
        db_index=True,
        help_text=_('Cryptographically secure, non-guessable public identifier (e.g., SIG-2026-XXXXXXXX).'),
    )
    verification_token = models.CharField(
        _('verification token'),
        max_length=128,
        unique=True,
        db_index=True,
        help_text=_('Secure opaque token for public URL lookup.'),
    )
    snapshot_hash = models.CharField(
        _('snapshot SHA-256 hash'),
        max_length=64,
        db_index=True,
        help_text=_('Cryptographic SHA-256 hash of the complete canonical snapshot.'),
    )
    payload_hash = models.CharField(
        _('payload SHA-256 hash'),
        max_length=64,
        db_index=True,
        help_text=_('SHA-256 checksum of the canonical task payload that was signed.'),
    )
    signature_value = models.TextField(
        _('digital signature value'),
        help_text=_('Base64-encoded asymmetric digital signature (Ed25519).'),
    )
    algorithm = models.CharField(
        _('cryptographic algorithm'),
        max_length=50,
        default='Ed25519',
    )
    key_version = models.CharField(
        _('key version'),
        max_length=32,
        default='v1',
    )
    public_key_reference = models.TextField(
        _('public key reference / PEM'),
        blank=True,
        help_text=_('PEM or Base64 encoding of the public key for historical verification.'),
    )
    signed_pdf = models.FileField(
        _('signed PDF document'),
        upload_to='signatures/pdf/%Y/%m/',
        blank=True,
        null=True,
        help_text=_('Officially generated PDF document with electronic signature seal and QR code.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    # Revocation metadata
    revoked_at = models.DateTimeField(_('revoked at'), null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('revoked by'),
        on_delete=models.SET_NULL,
        related_name='revoked_signatures',
        null=True,
        blank=True,
    )
    revocation_reason = models.TextField(_('revocation reason'), blank=True)

    class Meta:
        ordering = ['-signed_at']
        indexes = [
            models.Index(fields=['task', 'status']),
            models.Index(fields=['signer', 'status']),
            models.Index(fields=['signed_at']),
            models.Index(fields=['verification_id']),
            models.Index(fields=['verification_token']),
        ]
        verbose_name = _('electronic signature')
        verbose_name_plural = _('electronic signatures')

    def __str__(self):
        target = self.task.task_number if self.task else (self.kpi_period.code if self.kpi_period else self.verification_id)
        return f"{self.verification_id} [{self.get_status_display()}] — {target}"

    @property
    def is_valid(self) -> bool:
        return self.status == self.Status.SIGNED and self.revoked_at is None


class SignatureSnapshot(models.Model):
    """
    Immutable snapshot containing the exact canonical representation of the task record
    at the time of digital signing.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signature = models.OneToOneField(
        ElectronicSignature,
        verbose_name=_('electronic signature'),
        on_delete=models.CASCADE,
        related_name='snapshot',
    )
    canonical_payload = models.JSONField(
        _('canonical payload'),
        help_text=_('Deterministic canonical JSON representation of the signed task.'),
    )
    payload_hash = models.CharField(
        _('payload hash'),
        max_length=64,
        help_text=_('SHA-256 checksum matching the signature record.'),
    )
    schema_version = models.PositiveIntegerField(_('schema version'), default=1)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('signature snapshot')
        verbose_name_plural = _('signature snapshots')

    def __str__(self):
        return f"Snapshot v{self.schema_version} for {self.signature.verification_id}"


class SignatureVerificationEvent(models.Model):
    """
    Audit log record for all electronic signature verification attempts.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signature = models.ForeignKey(
        ElectronicSignature,
        verbose_name=_('electronic signature'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verification_events',
    )
    verification_id = models.CharField(_('verification ID requested'), max_length=64, db_index=True)
    is_valid = models.BooleanField(_('verification passed'), default=False)
    failure_reason = models.CharField(_('failure reason'), max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(_('IP address'), null=True, blank=True)
    user_agent = models.TextField(_('user agent'), blank=True)
    verified_at = models.DateTimeField(_('verified at'), auto_now_add=True)

    class Meta:
        ordering = ['-verified_at']
        indexes = [
            models.Index(fields=['verification_id', 'verified_at']),
            models.Index(fields=['is_valid', 'verified_at']),
        ]
        verbose_name = _('signature verification event')
        verbose_name_plural = _('signature verification events')

    def __str__(self):
        res = 'VALID' if self.is_valid else f'FAIL: {self.failure_reason}'
        return f"Verify {self.verification_id} at {self.verified_at:%Y-%m-%d %H:%M} [{res}]"
