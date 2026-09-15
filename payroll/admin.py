from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from payroll.models import (
    CompensationComponent,
    KPIPayrollRule,
    PayrollAdjustment,
    PayrollLine,
    PayrollPeriod,
    PayrollPermissionConfig,
    PayrollRecord,
    PayrollTaxRule,
    SalaryBand,
    SalaryHistory,
    SalaryProfile,
)


@admin.register(SalaryProfile)
class SalaryProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'base_salary', 'currency', 'effective_from', 'effective_to', 'salary_type', 'status']
    list_filter = ['status', 'salary_type', 'currency']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SalaryHistory)
class SalaryHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'previous_salary', 'new_salary', 'currency', 'effective_from', 'changed_by', 'created_at']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    readonly_fields = ['user', 'previous_salary', 'new_salary', 'currency', 'effective_from', 'reason', 'changed_by', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SalaryBand)
class SalaryBandAdmin(admin.ModelAdmin):
    list_display = ['grade', 'min_salary', 'max_salary', 'currency', 'effective_from', 'effective_to', 'is_active']
    list_filter = ['is_active', 'grade']


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'period_type', 'start_date', 'end_date', 'status', 'created_by', 'approved_by']
    list_filter = ['status', 'period_type']
    search_fields = ['name', 'code']


class PayrollLineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0
    readonly_fields = ['name_snapshot', 'component_type', 'calculation_type', 'rate_or_value', 'amount', 'taxable']


@admin.register(PayrollRecord)
class PayrollRecordAdmin(admin.ModelAdmin):
    list_display = [
        'employee_name_snapshot',
        'period',
        'base_salary',
        'kpi_bonus',
        'gross_salary',
        'tax_total',
        'net_salary',
        'status',
        'payment_status',
    ]
    list_filter = ['status', 'payment_status', 'period']
    search_fields = ['employee_name_snapshot', 'employee_username_snapshot']
    inlines = [PayrollLineInline]


@admin.register(CompensationComponent)
class CompensationComponentAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'component_type', 'calculation_type', 'default_value', 'is_taxable', 'is_active']
    list_filter = ['component_type', 'calculation_type', 'is_taxable', 'is_active']
    search_fields = ['name', 'code']


@admin.register(PayrollAdjustment)
class PayrollAdjustmentAdmin(admin.ModelAdmin):
    list_display = ['employee', 'type', 'amount', 'period', 'status', 'created_by', 'approved_by', 'created_at']
    list_filter = ['type', 'status']
    search_fields = ['employee__username', 'employee__first_name', 'reason']


@admin.register(PayrollTaxRule)
class PayrollTaxRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'percentage', 'fixed_amount', 'applies_to', 'effective_from', 'is_active']
    list_filter = ['applies_to', 'is_active']
    search_fields = ['name', 'code']


@admin.register(KPIPayrollRule)
class KPIPayrollRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'min_score', 'max_score', 'bonus_type', 'bonus_value', 'is_active']
    list_filter = ['bonus_type', 'is_active']
    search_fields = ['name']


@admin.register(PayrollPermissionConfig)
class PayrollPermissionConfigAdmin(admin.ModelAdmin):
    list_display = ['user', 'can_view_payroll', 'can_manage_salary', 'can_calculate_payroll', 'can_approve_payroll', 'can_mark_paid']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']

