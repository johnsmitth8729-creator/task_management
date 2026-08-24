from django.contrib import admin

from .models import Department, DepartmentResponsibility, Position


class DepartmentResponsibilityInline(admin.TabularInline):
    model = DepartmentResponsibility
    extra = 1
    fk_name = 'department'


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'head', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code', 'description')
    ordering = ('name',)
    inlines = [DepartmentResponsibilityInline]


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'department', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active', 'department')
    search_fields = ('name', 'code', 'description')
    ordering = ('name',)


@admin.register(DepartmentResponsibility)
class DepartmentResponsibilityAdmin(admin.ModelAdmin):
    list_display = ('vice_rector', 'department', 'start_date', 'end_date', 'is_active')
    list_filter = ('is_active', 'vice_rector', 'department')
    search_fields = ('vice_rector__username', 'vice_rector__first_name', 'department__name')
    ordering = ('-start_date',)
