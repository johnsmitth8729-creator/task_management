from django.contrib import admin

from tasks.models import (
    RecurringTask,
    SubTask,
    Task,
    TaskAssignment,
    TaskDependency,
    TaskHistory,
    TaskTemplate,
    TaskType,
)


class TaskAssignmentInline(admin.TabularInline):
    model = TaskAssignment
    extra = 1
    raw_id_fields = ('user', 'assigned_by')


class SubTaskInline(admin.TabularInline):
    model = SubTask
    extra = 1
    raw_id_fields = ('assignee',)


class TaskDependencyInline(admin.TabularInline):
    model = TaskDependency
    fk_name = 'task'
    extra = 1
    raw_id_fields = ('depends_on',)


@admin.register(TaskType)
class TaskTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        'task_number',
        'title',
        'responsible_department',
        'task_type',
        'priority',
        'complexity',
        'status',
        'progress',
        'deadline',
        'creator',
        'created_at',
    )
    list_filter = ('status', 'priority', 'complexity', 'responsible_department', 'task_type')
    search_fields = ('task_number', 'title', 'description')
    raw_id_fields = ('creator', 'responsible_department', 'task_type', 'cancelled_by')
    inlines = [TaskAssignmentInline, SubTaskInline, TaskDependencyInline]
    date_hierarchy = 'created_at'


@admin.register(TaskAssignment)
class TaskAssignmentAdmin(admin.ModelAdmin):
    list_display = ('task', 'user', 'is_primary', 'assigned_by', 'assigned_at')
    list_filter = ('is_primary',)
    search_fields = ('task__task_number', 'task__title', 'user__username', 'user__first_name', 'user__last_name')
    raw_id_fields = ('task', 'user', 'assigned_by')


@admin.register(SubTask)
class SubTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'parent_task', 'status', 'progress', 'assignee', 'deadline')
    list_filter = ('status',)
    search_fields = ('title', 'parent_task__task_number', 'parent_task__title')
    raw_id_fields = ('parent_task', 'assignee')


@admin.register(TaskDependency)
class TaskDependencyAdmin(admin.ModelAdmin):
    list_display = ('task', 'depends_on', 'dependency_type', 'created_at')
    list_filter = ('dependency_type',)
    raw_id_fields = ('task', 'depends_on')


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'task_type', 'default_priority', 'default_complexity', 'default_duration_days', 'is_active', 'created_by')
    list_filter = ('is_active', 'default_priority', 'default_complexity')
    search_fields = ('name', 'description')
    raw_id_fields = ('task_type', 'created_by')


@admin.register(RecurringTask)
class RecurringTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'responsible_department', 'frequency', 'start_date', 'end_date', 'next_run_at', 'is_active')
    list_filter = ('frequency', 'is_active', 'responsible_department')
    search_fields = ('title',)
    raw_id_fields = ('template', 'responsible_department', 'created_by')


@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    list_display = ('task', 'actor', 'event_type', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('task__task_number', 'task__title', 'actor__username')
    raw_id_fields = ('task', 'actor')
    readonly_fields = ('task', 'actor', 'event_type', 'old_value', 'new_value', 'created_at')
