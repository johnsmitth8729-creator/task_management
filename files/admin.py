from django.contrib import admin
from files.models import TaskFile, TaskFolder, TaskReport


@admin.register(TaskFolder)
class TaskFolderAdmin(admin.ModelAdmin):
    list_display = ['name', 'task', 'parent_folder', 'created_by', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'task__task_number', 'task__title']


@admin.register(TaskFile)
class TaskFileAdmin(admin.ModelAdmin):
    list_display = ['original_filename', 'task', 'folder', 'category', 'file_extension', 'file_size', 'uploaded_by', 'version', 'is_active', 'created_at']
    list_filter = ['category', 'file_extension', 'is_active', 'created_at']
    search_fields = ['original_filename', 'task__task_number', 'task__title', 'checksum']


@admin.register(TaskReport)
class TaskReportAdmin(admin.ModelAdmin):
    list_display = ['title', 'task', 'author', 'status', 'version', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['title', 'task__task_number', 'summary']
