from django.urls import path

from tasks.views import (
    DependencyAddView,
    DependencyRemoveView,
    SubTaskCreateView,
    SubTaskDeleteView,
    SubTaskUpdateView,
    TaskAddNoteView,
    TaskArchiveView,
    TaskAssignView,
    TaskCancelView,
    TaskCreateView,
    TaskDeleteView,
    TaskDetailView,
    TaskListView,
    TaskStatusChangeView,
    TaskTemplateCreateView,
    TaskTemplateListView,
    TaskTemplateUpdateView,
    TaskTemplateUseView,
    TaskTypeCreateView,
    TaskTypeListView,
    TaskTypeToggleView,
    TaskTypeUpdateView,
    TaskUnassignView,
    TaskUpdateView,
)

urlpatterns = [
    # Task CRUD
    path('tasks/', TaskListView.as_view(), name='task_list'),
    path('tasks/create/', TaskCreateView.as_view(), name='task_create'),
    path('tasks/<uuid:pk>/', TaskDetailView.as_view(), name='task_detail'),
    path('tasks/<uuid:pk>/edit/', TaskUpdateView.as_view(), name='task_edit'),
    path('tasks/<uuid:pk>/delete/', TaskDeleteView.as_view(), name='task_delete'),
    path('tasks/<uuid:pk>/cancel/', TaskCancelView.as_view(), name='task_cancel'),
    path('tasks/<uuid:pk>/archive/', TaskArchiveView.as_view(), name='task_archive'),
    path('tasks/<uuid:pk>/status/', TaskStatusChangeView.as_view(), name='task_status_change'),
    path('tasks/<uuid:pk>/assign/', TaskAssignView.as_view(), name='task_assign'),
    path('tasks/<uuid:pk>/unassign/<uuid:assignment_pk>/', TaskUnassignView.as_view(), name='task_unassign'),
    path('tasks/<uuid:pk>/notes/', TaskAddNoteView.as_view(), name='task_add_note'),

    # Subtasks
    path('tasks/<uuid:pk>/subtasks/create/', SubTaskCreateView.as_view(), name='subtask_create'),
    path('tasks/<uuid:pk>/subtasks/<uuid:st_pk>/edit/', SubTaskUpdateView.as_view(), name='subtask_edit'),
    path('tasks/<uuid:pk>/subtasks/<uuid:st_pk>/delete/', SubTaskDeleteView.as_view(), name='subtask_delete'),

    # Dependencies
    path('tasks/<uuid:pk>/dependencies/add/', DependencyAddView.as_view(), name='dependency_add'),
    path('tasks/<uuid:pk>/dependencies/<uuid:dep_pk>/remove/', DependencyRemoveView.as_view(), name='dependency_remove'),

    # Task Types
    path('tasks/types/', TaskTypeListView.as_view(), name='task_type_list'),
    path('tasks/types/create/', TaskTypeCreateView.as_view(), name='task_type_create'),
    path('tasks/types/<uuid:pk>/edit/', TaskTypeUpdateView.as_view(), name='task_type_edit'),
    path('tasks/types/<uuid:pk>/toggle/', TaskTypeToggleView.as_view(), name='task_type_toggle'),

    # Task Templates
    path('tasks/templates/', TaskTemplateListView.as_view(), name='task_template_list'),
    path('tasks/templates/create/', TaskTemplateCreateView.as_view(), name='task_template_create'),
    path('tasks/templates/<uuid:pk>/edit/', TaskTemplateUpdateView.as_view(), name='task_template_edit'),
    path('tasks/templates/<uuid:pk>/use/', TaskTemplateUseView.as_view(), name='task_template_use'),
]
