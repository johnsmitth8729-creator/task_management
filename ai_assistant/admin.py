from django.contrib import admin
from ai_assistant.models import (
    AIConversation,
    AIMessage,
    ExecutiveBriefing,
    ManagementRiskIndicator,
)


class AIMessageInline(admin.TabularInline):
    model = AIMessage
    extra = 0
    readonly_fields = ['role', 'content', 'created_at']


@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'created_at', 'updated_at']
    search_fields = ['title', 'user__username']
    inlines = [AIMessageInline]


@admin.register(ManagementRiskIndicator)
class ManagementRiskIndicatorAdmin(admin.ModelAdmin):
    list_display = ['title', 'risk_type', 'severity', 'department', 'is_resolved', 'detected_at']
    list_filter = ['severity', 'risk_type', 'is_resolved']
    search_fields = ['title', 'description', 'department__name']


@admin.register(ExecutiveBriefing)
class ExecutiveBriefingAdmin(admin.ModelAdmin):
    list_display = ['title', 'generated_for', 'period_start', 'period_end', 'created_at']
    search_fields = ['title', 'generated_for__username']
