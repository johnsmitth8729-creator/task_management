from django.contrib import admin
from analytics.models import AnalyticsThresholdConfig, SavedReportConfiguration


@admin.register(AnalyticsThresholdConfig)
class AnalyticsThresholdConfigAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'is_active',
        'max_acceptable_overdue_tasks',
        'min_completion_rate_percent',
        'min_ontime_rate_percent',
        'min_kpi_score_percent',
        'updated_at',
    )
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(SavedReportConfiguration)
class SavedReportConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'report_type', 'is_system_preset', 'created_by', 'created_at')
    list_filter = ('report_type', 'is_system_preset')
    search_fields = ('name', 'description')
