from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target_repr', 'ip_address')
    list_filter = ('action', 'created_at')
    search_fields = ('target_repr', 'actor__username', 'actor__first_name', 'actor__last_name')
    readonly_fields = ('id', 'actor', 'action', 'target_repr', 'details', 'ip_address', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
