from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from signatures.models import (
    ElectronicSignature,
    SignatureSnapshot,
    SignatureVerificationEvent,
)


class SignatureSnapshotInline(admin.StackedInline):
    model = SignatureSnapshot
    extra = 0
    can_delete = False
    readonly_fields = ('canonical_payload', 'payload_hash', 'schema_version', 'created_at')

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ElectronicSignature)
class ElectronicSignatureAdmin(admin.ModelAdmin):
    list_display = (
        'verification_id',
        'task',
        'signer',
        'signature_type',
        'status',
        'signed_at',
        'algorithm',
        'key_version',
    )
    list_filter = ('status', 'signature_type', 'algorithm', 'key_version')
    search_fields = ('verification_id', 'task__task_number', 'task__title', 'signer__username', 'signer__first_name', 'signer__last_name')
    readonly_fields = (
        'id',
        'task',
        'signer',
        'signature_type',
        'signed_at',
        'verification_id',
        'verification_token',
        'snapshot_hash',
        'payload_hash',
        'signature_value',
        'algorithm',
        'key_version',
        'public_key_reference',
        'created_at',
    )
    inlines = [SignatureSnapshotInline]

    fieldsets = (
        (_('Identity & Status'), {
            'fields': ('verification_id', 'status', 'task', 'signer', 'signature_type', 'signed_at'),
        }),
        (_('Cryptographic & Integrity Details'), {
            'fields': (
                'algorithm',
                'key_version',
                'payload_hash',
                'snapshot_hash',
                'signature_value',
                'public_key_reference',
                'verification_token',
            ),
            'classes': ('collapse',),
        }),
        (_('Revocation Metadata'), {
            'fields': ('revoked_at', 'revoked_by', 'revocation_reason'),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SignatureSnapshot)
class SignatureSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'signature', 'schema_version', 'created_at')
    search_fields = ('signature__verification_id', 'payload_hash')
    readonly_fields = ('id', 'signature', 'canonical_payload', 'payload_hash', 'schema_version', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SignatureVerificationEvent)
class SignatureVerificationEventAdmin(admin.ModelAdmin):
    list_display = ('verification_id', 'is_valid', 'failure_reason', 'ip_address', 'verified_at')
    list_filter = ('is_valid', 'verified_at')
    search_fields = ('verification_id', 'failure_reason', 'ip_address')
    readonly_fields = ('id', 'signature', 'verification_id', 'is_valid', 'failure_reason', 'ip_address', 'user_agent', 'verified_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
