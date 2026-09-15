from django.urls import path

from files.views import (
    TaskExportDOCXView,
    TaskExportPDFView,
    TaskExportXLSXView,
    TaskFileDeleteView,
    TaskFileDownloadView,
    TaskFileInlineView,
    TaskFileMoveView,
    TaskFileUploadView,
    TaskFolderCreateView,
    TaskFolderDeleteView,
    TaskFolderRenameView,
    TaskReportCreateView,
    TaskReportDeleteView,
    TaskReportDetailView,
    TaskReportExportDOCXView,
    TaskReportExportPDFView,
    TaskReportExportXLSXView,
    TaskReportListView,
    TaskReportUpdateView,
)

urlpatterns = [
    # File operations
    path('files/tasks/<uuid:task_pk>/upload/', TaskFileUploadView.as_view(), name='task_file_upload'),
    path('files/<uuid:pk>/download/', TaskFileDownloadView.as_view(), name='task_file_download'),
    path('files/<uuid:pk>/view/', TaskFileInlineView.as_view(), name='task_file_inline'),
    path('files/<uuid:pk>/delete/', TaskFileDeleteView.as_view(), name='task_file_delete'),
    path('files/<uuid:pk>/move/', TaskFileMoveView.as_view(), name='task_file_move'),

    # Folder operations
    path('files/tasks/<uuid:task_pk>/folders/create/', TaskFolderCreateView.as_view(), name='task_folder_create'),
    path('files/folders/<uuid:pk>/rename/', TaskFolderRenameView.as_view(), name='task_folder_rename'),
    path('files/folders/<uuid:pk>/delete/', TaskFolderDeleteView.as_view(), name='task_folder_delete'),

    # Report operations
    path('files/tasks/<uuid:task_pk>/reports/', TaskReportListView.as_view(), name='task_reports'),
    path('files/tasks/<uuid:task_pk>/reports/create/', TaskReportCreateView.as_view(), name='task_report_create'),
    path('files/reports/<uuid:pk>/', TaskReportDetailView.as_view(), name='task_report_detail'),
    path('files/reports/<uuid:pk>/edit/', TaskReportUpdateView.as_view(), name='task_report_edit'),
    path('files/reports/<uuid:pk>/delete/', TaskReportDeleteView.as_view(), name='task_report_delete'),

    # Report exports
    path('files/reports/<uuid:pk>/export/pdf/', TaskReportExportPDFView.as_view(), name='task_report_export_pdf'),
    path('files/reports/<uuid:pk>/export/docx/', TaskReportExportDOCXView.as_view(), name='task_report_export_docx'),
    path('files/reports/<uuid:pk>/export/xlsx/', TaskReportExportXLSXView.as_view(), name='task_report_export_xlsx'),

    # Task completion/summary exports
    path('files/tasks/<uuid:pk>/export/pdf/', TaskExportPDFView.as_view(), name='task_export_pdf'),
    path('files/tasks/<uuid:pk>/export/docx/', TaskExportDOCXView.as_view(), name='task_export_docx'),
    path('files/tasks/<uuid:pk>/export/xlsx/', TaskExportXLSXView.as_view(), name='task_export_xlsx'),
]
