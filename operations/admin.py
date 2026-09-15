from django.contrib import admin
from operations.models import (
    DocumentVersion,
    RequestApprovalStep,
    RequestCategory,
    RequestType,
    UniversityDocument,
    UniversityRequest,
)


@admin.register(RequestCategory)
class RequestCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']


@admin.register(RequestType)
class RequestTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'code', 'sla_resolution_hours', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'code']


class RequestApprovalStepInline(admin.TabularInline):
    model = RequestApprovalStep
    extra = 0
    readonly_fields = ['step_number', 'approver_role', 'assigned_approver', 'status', 'decided_by', 'decided_at']


@admin.register(UniversityRequest)
class UniversityRequestAdmin(admin.ModelAdmin):
    list_display = ['request_number', 'subject', 'request_type', 'requester', 'department', 'status', 'current_step_number', 'created_at']
    list_filter = ['status', 'request_type__category', 'is_urgent']
    search_fields = ['request_number', 'subject', 'requester__username', 'requester__email']
    inlines = [RequestApprovalStepInline]


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    readonly_fields = ['version_number', 'file', 'changelog', 'uploaded_by', 'created_at']


@admin.register(UniversityDocument)
class UniversityDocumentAdmin(admin.ModelAdmin):
    list_display = ['doc_number', 'title', 'document_type', 'version', 'status', 'effective_date', 'created_at']
    list_filter = ['document_type', 'status']
    search_fields = ['doc_number', 'title', 'description']
    inlines = [DocumentVersionInline]
