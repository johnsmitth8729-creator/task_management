import mimetypes
import os

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.models import AuditLog, log_audit
from files.exports import (
    export_report_docx,
    export_report_pdf,
    export_report_xlsx,
    export_task_docx,
    export_task_pdf,
    export_task_xlsx,
)
from files.forms import TaskFileUploadForm, TaskFolderForm, TaskReportForm
from files.models import TaskFile, TaskFolder, TaskReport
from files.permissions import (
    can_create_report,
    can_delete_file,
    can_delete_report,
    can_download_file,
    can_edit_report,
    can_manage_folders,
    can_upload_task_file,
    can_view_report,
    can_view_task_files,
)
from files.services import (
    create_task_folder,
    create_task_report,
    delete_task_folder,
    move_task_file,
    rename_task_folder,
    soft_delete_task_file,
    update_task_report,
    upload_task_file,
)
from tasks.models import Task, TaskAssignment, TaskSubmission
from tasks.permissions import can_view_task


class FilesLoginMixin(LoginRequiredMixin):
    """All file and report operations require authentication."""
    pass


# ---------------------------------------------------------------------------
# File Upload, Download & Management Views
# ---------------------------------------------------------------------------

class TaskFileUploadView(FilesLoginMixin, View):
    """POST: Handles uploading one or multiple files attached to a Task."""

    def post(self, request, task_pk):
        task = get_object_or_404(Task, pk=task_pk)
        if not can_upload_task_file(request.user, task):
            raise PermissionDenied(_('You do not have permission to upload files to this task.'))

        # Optional folder
        folder_id = request.POST.get('folder')
        folder = None
        if folder_id:
            folder = TaskFolder.objects.filter(pk=folder_id, task=task, is_active=True).first()

        # Optional assignment / category / description
        assignment_id = request.POST.get('assignment')
        assignment = None
        if assignment_id:
            assignment = TaskAssignment.objects.filter(pk=assignment_id, task=task).first()

        category = request.POST.get('category', TaskFile.Category.WORK_EVIDENCE)
        description = request.POST.get('description', '')

        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        if not files:
            messages.error(request, _('Please select at least one file to upload.'))
            return redirect(request.META.get('HTTP_REFERER', 'task_list'))

        uploaded_count = 0
        for file_obj in files:
            try:
                upload_task_file(
                    actor=request.user,
                    task=task,
                    file_obj=file_obj,
                    description=description,
                    folder=folder,
                    assignment=assignment,
                    category=category,
                    request=request,
                )
                uploaded_count += 1
            except ValidationError as e:
                messages.error(request, f"{getattr(file_obj, 'name', 'File')}: {str(e.message)}")

        if uploaded_count > 0:
            messages.success(
                request,
                _('Successfully uploaded {count} file(s).').format(count=uploaded_count)
            )

        return redirect(request.META.get('HTTP_REFERER', 'task_list'))


class TaskFileDownloadView(FilesLoginMixin, View):
    """GET: Protected file download endpoint. Enforces RBAC & IDOR guards."""

    def get(self, request, pk):
        task_file = get_object_or_404(TaskFile.objects.select_related('task'), pk=pk)

        if not can_download_file(request.user, task_file):
            raise PermissionDenied(_('You do not have permission to download this file.'))

        if not task_file.file or not os.path.exists(task_file.file.path):
            raise Http404(_('File not found on storage server.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.FILE_DOWNLOADED,
            target_repr=f"Downloaded '{task_file.original_filename}' from {task_file.task.task_number}",
            details={'file_id': str(task_file.id), 'filename': task_file.original_filename},
            request=request,
        )

        response = FileResponse(open(task_file.file.path, 'rb'), as_attachment=True, filename=task_file.original_filename)
        if task_file.content_type:
            response['Content-Type'] = task_file.content_type
        return response


class TaskFileInlineView(FilesLoginMixin, View):
    """GET: Protected inline viewing for images, PDFs, and video formats in browser."""

    def get(self, request, pk):
        task_file = get_object_or_404(TaskFile.objects.select_related('task'), pk=pk)

        if not can_download_file(request.user, task_file):
            raise PermissionDenied(_('You do not have permission to view this file.'))

        if not task_file.file or not os.path.exists(task_file.file.path):
            raise Http404(_('File not found on storage server.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.FILE_DOWNLOADED,
            target_repr=f"Viewed inline '{task_file.original_filename}' from {task_file.task.task_number}",
            details={'file_id': str(task_file.id), 'inline': True},
            request=request,
        )

        content_type = task_file.content_type or 'application/octet-stream'
        response = FileResponse(open(task_file.file.path, 'rb'), as_attachment=False, filename=task_file.original_filename)
        response['Content-Type'] = content_type
        response['Content-Disposition'] = f'inline; filename="{task_file.original_filename}"'
        return response


class TaskFileDeleteView(FilesLoginMixin, View):
    """POST: Soft delete a file with confirmation."""

    def post(self, request, pk):
        task_file = get_object_or_404(TaskFile.objects.select_related('task'), pk=pk)
        if not can_delete_file(request.user, task_file):
            raise PermissionDenied(_('You do not have permission to delete this file.'))

        filename = task_file.original_filename
        try:
            soft_delete_task_file(request.user, task_file, request=request)
            messages.success(request, _('File "{filename}" was successfully deleted.').format(filename=filename))
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect(request.META.get('HTTP_REFERER', 'task_list'))


class TaskFileMoveView(FilesLoginMixin, View):
    """POST: Move file to a different folder."""

    def post(self, request, pk):
        task_file = get_object_or_404(TaskFile.objects.select_related('task'), pk=pk)
        folder_id = request.POST.get('target_folder')
        target_folder = None
        if folder_id:
            target_folder = get_object_or_404(TaskFolder, pk=folder_id, task=task_file.task, is_active=True)

        try:
            move_task_file(request.user, task_file, target_folder, request=request)
            messages.success(
                request,
                _('Moved file to "{folder}".').format(folder=target_folder.name if target_folder else _('Root'))
            )
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect(request.META.get('HTTP_REFERER', 'task_list'))


# ---------------------------------------------------------------------------
# Folder Views
# ---------------------------------------------------------------------------

class TaskFolderCreateView(FilesLoginMixin, View):
    """POST: Create a logical folder in task."""

    def post(self, request, task_pk):
        task = get_object_or_404(Task, pk=task_pk)
        name = request.POST.get('name', '').strip()
        parent_id = request.POST.get('parent_folder')
        parent_folder = None
        if parent_id:
            parent_folder = TaskFolder.objects.filter(pk=parent_id, task=task, is_active=True).first()

        try:
            folder = create_task_folder(request.user, task, name, parent_folder=parent_folder, request=request)
            messages.success(request, _('Folder "{name}" created successfully.').format(name=folder.name))
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect(request.META.get('HTTP_REFERER', 'task_list'))


class TaskFolderRenameView(FilesLoginMixin, View):
    """POST: Rename a folder."""

    def post(self, request, pk):
        folder = get_object_or_404(TaskFolder.objects.select_related('task'), pk=pk)
        new_name = request.POST.get('name', '').strip()
        try:
            rename_task_folder(request.user, folder, new_name, request=request)
            messages.success(request, _('Folder renamed successfully.'))
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect(request.META.get('HTTP_REFERER', 'task_list'))


class TaskFolderDeleteView(FilesLoginMixin, View):
    """POST: Delete a folder."""

    def post(self, request, pk):
        folder = get_object_or_404(TaskFolder.objects.select_related('task'), pk=pk)
        try:
            delete_task_folder(request.user, folder, request=request)
            messages.success(request, _('Folder deleted successfully.'))
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect(request.META.get('HTTP_REFERER', 'task_list'))


# ---------------------------------------------------------------------------
# Report Views
# ---------------------------------------------------------------------------

class TaskReportListView(FilesLoginMixin, ListView):
    """Lists structured reports for a task."""
    template_name = 'files/report_list.html'
    context_object_name = 'reports'
    paginate_by = 20

    def get_queryset(self):
        self.task = get_object_or_404(Task.objects.select_related('responsible_department'), pk=self.kwargs['task_pk'])
        if not can_view_task_files(self.request.user, self.task):
            raise PermissionDenied(_('You do not have permission to view reports for this task.'))

        return TaskReport.objects.filter(task=self.task).select_related('author').order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['task'] = self.task
        ctx['can_create_report'] = can_create_report(self.request.user, self.task)
        return ctx


class TaskReportCreateView(FilesLoginMixin, View):
    """GET/POST: Create a structured work report."""

    def get(self, request, task_pk):
        task = get_object_or_404(Task.objects.select_related('responsible_department'), pk=task_pk)
        if not can_create_report(request.user, task):
            raise PermissionDenied(_('You do not have permission to create reports on this task.'))

        form = TaskReportForm(initial={'title': f"{_('Work Report')} — {task.title}"})
        return render(request, 'files/report_form.html', {'form': form, 'task': task, 'is_create': True})

    def post(self, request, task_pk):
        task = get_object_or_404(Task.objects.select_related('responsible_department'), pk=task_pk)
        if not can_create_report(request.user, task):
            raise PermissionDenied(_('You do not have permission to create reports on this task.'))

        form = TaskReportForm(request.POST)
        if form.is_valid():
            try:
                report = create_task_report(
                    actor=request.user,
                    task=task,
                    title=form.cleaned_data['title'],
                    summary=form.cleaned_data['summary'],
                    completed_work=form.cleaned_data['completed_work'],
                    results=form.cleaned_data['results'],
                    reporting_period=form.cleaned_data.get('reporting_period', ''),
                    problems=form.cleaned_data.get('problems', ''),
                    recommendations=form.cleaned_data.get('recommendations', ''),
                    conclusion=form.cleaned_data.get('conclusion', ''),
                    status=form.cleaned_data.get('status', TaskReport.Status.DRAFT),
                    request=request,
                )
                messages.success(request, _('Report "{title}" created successfully.').format(title=report.title))
                return redirect('task_report_detail', pk=report.pk)
            except ValidationError as e:
                form.add_error(None, e.message)

        return render(request, 'files/report_form.html', {'form': form, 'task': task, 'is_create': True})


class TaskReportDetailView(FilesLoginMixin, DetailView):
    """GET: View full structured report."""
    template_name = 'files/report_detail.html'
    context_object_name = 'report'

    def get_object(self):
        report = get_object_or_404(
            TaskReport.objects.select_related('task', 'task__responsible_department', 'author'),
            pk=self.kwargs['pk']
        )
        if not can_view_report(self.request.user, report):
            raise PermissionDenied(_('You do not have permission to view this report.'))
        return report

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        report = self.object
        ctx['task'] = report.task
        ctx['can_edit'] = can_edit_report(self.request.user, report)
        ctx['can_delete'] = can_delete_report(self.request.user, report)
        return ctx


class TaskReportUpdateView(FilesLoginMixin, View):
    """GET/POST: Edit a structured work report."""

    def get(self, request, pk):
        report = get_object_or_404(TaskReport.objects.select_related('task'), pk=pk)
        if not can_edit_report(request.user, report):
            raise PermissionDenied(_('You do not have permission to edit this report.'))

        form = TaskReportForm(instance=report)
        return render(request, 'files/report_form.html', {'form': form, 'task': report.task, 'report': report, 'is_create': False})

    def post(self, request, pk):
        report = get_object_or_404(TaskReport.objects.select_related('task'), pk=pk)
        if not can_edit_report(request.user, report):
            raise PermissionDenied(_('You do not have permission to edit this report.'))

        form = TaskReportForm(request.POST, instance=report)
        if form.is_valid():
            try:
                update_task_report(
                    actor=request.user,
                    report=report,
                    title=form.cleaned_data['title'],
                    summary=form.cleaned_data['summary'],
                    completed_work=form.cleaned_data['completed_work'],
                    results=form.cleaned_data['results'],
                    reporting_period=form.cleaned_data.get('reporting_period', ''),
                    problems=form.cleaned_data.get('problems', ''),
                    recommendations=form.cleaned_data.get('recommendations', ''),
                    conclusion=form.cleaned_data.get('conclusion', ''),
                    status=form.cleaned_data.get('status', report.status),
                    request=request,
                )
                messages.success(request, _('Report updated successfully.'))
                return redirect('task_report_detail', pk=report.pk)
            except ValidationError as e:
                form.add_error(None, e.message)

        return render(request, 'files/report_form.html', {'form': form, 'task': report.task, 'report': report, 'is_create': False})


class TaskReportDeleteView(FilesLoginMixin, View):
    """POST: Delete a draft work report."""

    def post(self, request, pk):
        report = get_object_or_404(TaskReport.objects.select_related('task'), pk=pk)
        if not can_delete_report(request.user, report):
            raise PermissionDenied(_('You do not have permission to delete this report.'))

        task_id = report.task_id
        title = report.title
        report.delete()

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.REPORT_DELETED,
            target_repr=f"Deleted report '{title}'",
            details={'report_id': str(pk), 'task_id': str(task_id)},
            request=request,
        )

        messages.success(request, _('Report "{title}" deleted successfully.').format(title=title))
        return redirect('task_reports', task_pk=task_id)


# ---------------------------------------------------------------------------
# Export Endpoints (PDF, DOCX, XLSX)
# ---------------------------------------------------------------------------

class TaskReportExportPDFView(FilesLoginMixin, View):
    """GET: Stream generated PDF for a TaskReport."""

    def get(self, request, pk):
        report = get_object_or_404(TaskReport.objects.select_related('task', 'task__responsible_department', 'author'), pk=pk)
        if not can_view_report(request.user, report):
            raise PermissionDenied(_('You do not have permission to export this report.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.REPORT_EXPORTED,
            target_repr=f"Exported PDF for report '{report.title}'",
            details={'report_id': str(report.id), 'format': 'pdf'},
            request=request,
        )

        pdf_buffer = export_report_pdf(report)
        response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
        filename = f"report_{report.task.task_number}_{report.id.hex[:8]}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TaskReportExportDOCXView(FilesLoginMixin, View):
    """GET: Stream generated DOCX for a TaskReport."""

    def get(self, request, pk):
        report = get_object_or_404(TaskReport.objects.select_related('task', 'task__responsible_department', 'author'), pk=pk)
        if not can_view_report(request.user, report):
            raise PermissionDenied(_('You do not have permission to export this report.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.REPORT_EXPORTED,
            target_repr=f"Exported DOCX for report '{report.title}'",
            details={'report_id': str(report.id), 'format': 'docx'},
            request=request,
        )

        docx_buffer = export_report_docx(report)
        response = HttpResponse(docx_buffer.read(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        filename = f"report_{report.task.task_number}_{report.id.hex[:8]}.docx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TaskReportExportXLSXView(FilesLoginMixin, View):
    """GET: Stream generated XLSX for a TaskReport."""

    def get(self, request, pk):
        report = get_object_or_404(TaskReport.objects.select_related('task', 'task__responsible_department', 'author'), pk=pk)
        if not can_view_report(request.user, report):
            raise PermissionDenied(_('You do not have permission to export this report.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.REPORT_EXPORTED,
            target_repr=f"Exported XLSX for report '{report.title}'",
            details={'report_id': str(report.id), 'format': 'xlsx'},
            request=request,
        )

        xlsx_buffer = export_report_xlsx(report)
        response = HttpResponse(xlsx_buffer.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        filename = f"report_{report.task.task_number}_{report.id.hex[:8]}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TaskExportPDFView(FilesLoginMixin, View):
    """GET: Stream generated Task Summary / Completion PDF."""

    def get(self, request, pk):
        task = get_object_or_404(Task.objects.select_related('responsible_department', 'creator'), pk=pk)
        if not can_view_task_files(request.user, task):
            raise PermissionDenied(_('You do not have permission to export this task.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.REPORT_EXPORTED,
            target_repr=f"Exported Task PDF for {task.task_number}",
            details={'task_id': str(task.id), 'format': 'pdf'},
            request=request,
        )

        pdf_buffer = export_task_pdf(task)
        response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
        filename = f"task_{task.task_number}_summary.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TaskExportDOCXView(FilesLoginMixin, View):
    """GET: Stream generated Task Summary DOCX."""

    def get(self, request, pk):
        task = get_object_or_404(Task.objects.select_related('responsible_department', 'creator'), pk=pk)
        if not can_view_task_files(request.user, task):
            raise PermissionDenied(_('You do not have permission to export this task.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.REPORT_EXPORTED,
            target_repr=f"Exported Task DOCX for {task.task_number}",
            details={'task_id': str(task.id), 'format': 'docx'},
            request=request,
        )

        docx_buffer = export_task_docx(task)
        response = HttpResponse(docx_buffer.read(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        filename = f"task_{task.task_number}_summary.docx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TaskExportXLSXView(FilesLoginMixin, View):
    """GET: Stream generated Task Summary XLSX."""

    def get(self, request, pk):
        task = get_object_or_404(Task.objects.select_related('responsible_department', 'creator'), pk=pk)
        if not can_view_task_files(request.user, task):
            raise PermissionDenied(_('You do not have permission to export this task.'))

        log_audit(
            actor=request.user,
            action=AuditLog.Actions.REPORT_EXPORTED,
            target_repr=f"Exported Task XLSX for {task.task_number}",
            details={'task_id': str(task.id), 'format': 'xlsx'},
            request=request,
        )

        xlsx_buffer = export_task_xlsx(task)
        response = HttpResponse(xlsx_buffer.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        filename = f"task_{task.task_number}_summary.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
