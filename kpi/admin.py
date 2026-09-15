from django.contrib import admin
from kpi.models import KPIAssignment, KPICategory, KPIDefinition, KPIPeriod, KPIResult


@admin.register(KPICategory)
class KPICategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['code', 'name']


@admin.register(KPIPeriod)
class KPIPeriodAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'period_type', 'start_date', 'end_date', 'status', 'is_active']
    list_filter = ['period_type', 'status', 'is_active']
    search_fields = ['code', 'name']


@admin.register(KPIDefinition)
class KPIDefinitionAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'category', 'measurement_type', 'target_value', 'weight', 'is_active']
    list_filter = ['category', 'measurement_type', 'is_active']
    search_fields = ['code', 'name']


@admin.register(KPIAssignment)
class KPIAssignmentAdmin(admin.ModelAdmin):
    list_display = ['user', 'kpi', 'period', 'target_value', 'weight', 'is_active']
    list_filter = ['period', 'is_active']
    search_fields = ['user__username', 'kpi__name', 'period__code']


@admin.register(KPIResult)
class KPIResultAdmin(admin.ModelAdmin):
    list_display = ['assignment', 'actual_value', 'raw_score', 'weighted_score', 'status', 'evaluated_by']
    list_filter = ['status']
    search_fields = ['assignment__user__username', 'assignment__kpi__name']
