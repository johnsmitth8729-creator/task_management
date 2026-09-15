from django.contrib import admin
from hr.models import EmployeeGrade, HRPermissionConfig


@admin.register(EmployeeGrade)
class EmployeeGradeAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'rank', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['code', 'name', 'description']


@admin.register(HRPermissionConfig)
class HRPermissionConfigAdmin(admin.ModelAdmin):
    list_display = ['user', 'can_view_employees', 'can_create_employees', 'can_edit_employees', 'can_deactivate_employees', 'can_view_kpi']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
