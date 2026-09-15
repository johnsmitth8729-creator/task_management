"""
Phase 4 — Workflow Views
Covers:
  - Employee dashboard & task workflow (incoming, in-progress, first-approval)
  - Department Head dashboard & monitoring
  - Assignment detail, accept, progress update, notes, submit
  - Dept head: task distribution (assign employees), first approval queue, submission view
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from accounts.models import User
from files.forms import TaskFileUploadForm, TaskFolderForm
from files.models import TaskFile, TaskFolder, TaskReport
from files.permissions import (
    can_create_report,
    can_manage_folders,
    can_upload_task_file,
)
from organization.models import Department
from tasks.models import (
    Task,
    TaskApproval,
    TaskAssignment,
    TaskDeadlineExtension,
    TaskNote,
    TaskSubmission,
)
from tasks.permissions import (
    can_accept_assignment,
    can_add_task_note,
    can_assign_employees_to_task,
    can_assign_task,
    can_edit_task,
    can_extend_task_deadline,
    can_final_approve_assignment,
    can_first_approve_assignment,
    can_first_reject_assignment,
    can_second_approve_assignment,
    can_second_reject_assignment,
    can_start_rework,
    can_submit_assignment,
    can_update_assignment_progress,
    can_view_submission,
    can_view_task,
    is_task_in_submission_or_approval,
)
from tasks.services import (
    accept_assignment,
    add_task_note,
    assign_task,
    extend_task_deadline,
    final_approve_assignment,
    final_reject_assignment,
    first_approve_assignment,
    first_reject_assignment,
    get_scoped_tasks,
    get_visible_task_notes,
    start_rework,
    submit_assignment,
    update_assignment_progress,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class WorkflowLoginMixin(LoginRequiredMixin):
    """All workflow views require authentication."""
    pass


def _get_assignment_or_403(request, assignment_pk):
    assignment = get_object_or_404(
        TaskAssignment.objects.select_related('task', 'task__responsible_department', 'task__creator', 'user', 'assigned_by'),
        pk=assignment_pk,
    )
    if not can_view_task(request.user, assignment.task):
        raise PermissionDenied(_('You do not have permission to view this assignment.'))
    return assignment


# ---------------------------------------------------------------------------
# ROLE-BASED DASHBOARD REDIRECT
# ---------------------------------------------------------------------------

class WorkflowDashboardRedirectView(WorkflowLoginMixin, View):
    """Redirect to unified tasks list."""
    def get(self, request, *args, **kwargs):
        return redirect('task_list')


# ===========================================================================
# EMPLOYEE WORKFLOW VIEWS
# ===========================================================================

class EmployeeDashboardView(WorkflowLoginMixin, TemplateView):
    template_name = 'workflow/employee_dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        from core.middleware import get_current_active_year
        active_year = get_current_active_year()

        assignments = TaskAssignment.objects.filter(
            user=user
        ).exclude(
            task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]
        ).select_related('task', 'task__responsible_department', 'task__creator')

        if active_year:
            assignments = assignments.filter(task__created_at__year=active_year)

        ctx['total_assignments'] = assignments.count()
        ctx['incoming_count'] = assignments.filter(
            assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED
        ).count()
        ctx['in_progress_count'] = assignments.filter(
            assignment_status=TaskAssignment.AssignmentStatus.IN_PROGRESS
        ).count()
        ctx['submitted_count'] = assignments.filter(
            assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED
        ).count()
        ctx['second_approval_count'] = assignments.filter(
            assignment_status=TaskAssignment.AssignmentStatus.SECOND_APPROVAL
        ).count()
        return ctx


class EmployeeIncomingView(WorkflowLoginMixin, ListView):
    template_name = 'workflow/employee_incoming.html'
    context_object_name = 'assignments'
    paginate_by = 20

    def get_queryset(self):
        from core.middleware import get_current_active_year
        active_year = get_current_active_year()
        qs = (
            TaskAssignment.objects
            .filter(user=self.request.user, assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED)
            .exclude(task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])
            .select_related('task', 'task__responsible_department', 'task__creator', 'assigned_by')
        )
        if active_year:
            qs = qs.filter(task__created_at__year=active_year)
        return qs.order_by('task__deadline', '-assigned_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        page_assignments = ctx.get('assignments', [])
        page_ids = [str(a.id) for a in page_assignments]
        if page_ids and hasattr(self.request, 'session'):
            seen_incoming = set(self.request.session.get('seen_incoming_tasks', []))
            seen_incoming.update(page_ids)
            self.request.session['seen_incoming_tasks'] = list(seen_incoming)
            self.request.session.modified = True
        return ctx


class EmployeeInProgressView(WorkflowLoginMixin, ListView):
    template_name = 'workflow/employee_inprogress.html'
    context_object_name = 'assignments'
    paginate_by = 20

    def get_queryset(self):
        from core.middleware import get_current_active_year
        active_year = get_current_active_year()
        qs = (
            TaskAssignment.objects
            .filter(user=self.request.user, assignment_status=TaskAssignment.AssignmentStatus.IN_PROGRESS)
            .exclude(task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])
            .select_related('task', 'task__responsible_department', 'task__creator', 'assigned_by')
        )
        if active_year:
            qs = qs.filter(task__created_at__year=active_year)
        return qs.order_by('task__deadline')


class EmployeeFirstApprovalView(WorkflowLoginMixin, ListView):
    template_name = 'workflow/employee_first_approval.html'
    context_object_name = 'assignments'
    paginate_by = 20

    def get_queryset(self):
        from core.middleware import get_current_active_year
        active_year = get_current_active_year()
        qs = (
            TaskAssignment.objects
            .filter(user=self.request.user, assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED)
            .exclude(task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])
            .select_related('task', 'task__responsible_department', 'task__creator')
        )
        if active_year:
            qs = qs.filter(task__created_at__year=active_year)
        return qs.order_by('-updated_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        page_assignments = ctx.get('assignments', [])
        page_ids = [str(a.id) for a in page_assignments]
        if page_ids and hasattr(self.request, 'session'):
            seen_apps = set(self.request.session.get('seen_submitted_approvals', []))
            seen_apps.update(page_ids)
            self.request.session['seen_submitted_approvals'] = list(seen_apps)
            self.request.session.modified = True
        return ctx


class EmployeeSecondApprovalView(WorkflowLoginMixin, ListView):
    template_name = 'workflow/employee_second_approval.html'
    context_object_name = 'assignments'
    paginate_by = 20

    def get_queryset(self):
        from core.middleware import get_current_active_year
        active_year = get_current_active_year()
        qs = (
            TaskAssignment.objects
            .filter(user=self.request.user, assignment_status=TaskAssignment.AssignmentStatus.SECOND_APPROVAL)
            .exclude(task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])
            .select_related('task', 'task__responsible_department', 'task__creator')
        )
        if active_year:
            qs = qs.filter(task__created_at__year=active_year)
        return qs.order_by('-updated_at')



# ---------------------------------------------------------------------------
# Assignment Detail (Employee Work Area)
# ---------------------------------------------------------------------------

class AssignmentDetailView(WorkflowLoginMixin, DetailView):
    template_name = 'workflow/assignment_detail.html'
    context_object_name = 'assignment'

    def get_object(self):
        return _get_assignment_or_403(self.request, self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        assignment = self.object
        task = assignment.task
        user = self.request.user

        ctx['task'] = task
        ctx['can_accept'] = can_accept_assignment(user, assignment)
        ctx['can_update_progress'] = can_update_assignment_progress(user, assignment)
        ctx['can_submit'] = can_submit_assignment(user, assignment)
        ctx['can_start_rework'] = can_start_rework(user, assignment)
        ctx['can_add_note'] = can_add_task_note(user, task, assignment)
        ctx['latest_rejection'] = task.approvals.filter(
            assignment=assignment,
            decision=TaskApproval.Decision.REJECTED,
        ).order_by('-created_at').first()

        # Notes scoped to this assignment and task-level notes with visibility filtering
        notes_qs = TaskNote.objects.filter(
            Q(assignment=assignment) | Q(task=task, assignment__isnull=True)
        ).select_related('author', 'author__position')
        if not (user.is_superuser or user.is_rector or user.is_vice_rector):
            if user.is_department_head:
                notes_qs = notes_qs.exclude(visibility=TaskNote.Visibility.MANAGEMENT)
            else:
                notes_qs = notes_qs.filter(
                    Q(visibility=TaskNote.Visibility.EMPLOYEE) | Q(author=user)
                )
        ctx['notes'] = notes_qs.order_by('-created_at')

        # Phase 6 — Work Evidence Files, Folders & Reports
        ctx['folders'] = TaskFolder.objects.filter(task=task, is_active=True).order_by('name')
        ctx['files'] = TaskFile.objects.filter(task=task, is_active=True).select_related('folder', 'uploaded_by').order_by('-created_at')
        ctx['reports'] = TaskReport.objects.filter(task=task).select_related('author').order_by('-created_at')
        ctx['can_upload_file'] = can_upload_task_file(user, task, assignment=assignment)
        ctx['can_manage_folders'] = can_manage_folders(user, task)
        ctx['can_create_report'] = can_create_report(user, task)
        ctx['file_upload_form'] = TaskFileUploadForm(task=task)
        ctx['folder_form'] = TaskFolderForm(task=task)

        # Latest submission for this assignment
        ctx['latest_submission'] = (
            TaskSubmission.objects
            .filter(assignment=assignment)
            .order_by('-version')
            .first()
        )

        # Task timeline (last 20 events)
        ctx['history'] = task.history.select_related('actor').order_by('-created_at')[:20]

        # Multi-employee view & management toggle
        ctx['all_assignments'] = (
            task.assignments
            .select_related('user', 'user__department', 'user__position')
            .order_by('-is_primary', 'user__first_name')
        )
        ctx['can_manage_task'] = (
            can_assign_task(user, task)
            or can_edit_task(user, task)
            or (task.creator_id == user.id)
            or user.is_superuser
            or user.can_act_as_rector
        )

        return ctx


# ---------------------------------------------------------------------------
# Accept Assignment
# ---------------------------------------------------------------------------

class AcceptAssignmentView(WorkflowLoginMixin, View):
    def post(self, request, pk):
        assignment = _get_assignment_or_403(request, pk)
        if not can_accept_assignment(request.user, assignment):
            raise PermissionDenied(_('You cannot accept this assignment.'))
        try:
            accept_assignment(request.user, assignment, request=request)
            messages.success(request, _('Task accepted. You can now start working on it.'))
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('assignment_detail', pk=pk)


# ---------------------------------------------------------------------------
# Update Assignment Progress
# ---------------------------------------------------------------------------

class UpdateProgressView(WorkflowLoginMixin, View):
    def post(self, request, pk):
        assignment = _get_assignment_or_403(request, pk)
        if not can_update_assignment_progress(request.user, assignment):
            raise PermissionDenied(_('You cannot update progress on this assignment.'))
        try:
            new_progress = int(request.POST.get('progress', 0))
            update_assignment_progress(request.user, assignment, new_progress, request=request)
            messages.success(request, _('Progress updated successfully.'))
        except (ValidationError, ValueError) as e:
            messages.error(request, getattr(e, 'message', str(e)))
        return redirect('assignment_detail', pk=pk)


# ---------------------------------------------------------------------------
# Add Work Note
# ---------------------------------------------------------------------------

class AddNoteView(WorkflowLoginMixin, View):
    def post(self, request, pk):
        assignment = _get_assignment_or_403(request, pk)
        task = assignment.task
        if not can_add_task_note(request.user, task, assignment):
            raise PermissionDenied(_('You cannot add notes to this assignment.'))
        content = request.POST.get('content', '').strip()
        try:
            add_task_note(request.user, task, content, assignment=assignment, request=request)
            messages.success(request, _('Note added successfully.'))
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('assignment_detail', pk=pk)


# ---------------------------------------------------------------------------
# Submit Assignment
# ---------------------------------------------------------------------------

class SubmitAssignmentView(WorkflowLoginMixin, View):
    def post(self, request, pk):
        assignment = _get_assignment_or_403(request, pk)
        if not can_submit_assignment(request.user, assignment):
            raise PermissionDenied(_('You cannot submit this assignment.'))
        submission_text = request.POST.get('submission_text', '').strip()
        try:
            submit_assignment(request.user, assignment, submission_text, request=request)
            messages.success(request, _('Task submitted for first approval successfully.'))
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('assignment_detail', pk=pk)


# ---------------------------------------------------------------------------
# Start / Resume Rework
# ---------------------------------------------------------------------------

class StartReworkView(WorkflowLoginMixin, View):
    def post(self, request, pk):
        assignment = _get_assignment_or_403(request, pk)
        if not can_start_rework(request.user, assignment):
            raise PermissionDenied(_('You cannot start rework on this assignment.'))
        try:
            start_rework(request.user, assignment, request=request)
            messages.success(request, _('Rework started. You can now update progress, add notes, and submit a new version.'))
        except ValidationError as e:
            messages.error(request, getattr(e, 'message', str(e)))
        return redirect('assignment_detail', pk=pk)


# ===========================================================================
# DEPARTMENT HEAD WORKFLOW VIEWS
# ===========================================================================

class DeptHeadRequiredMixin(WorkflowLoginMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_department_head or request.user.is_rector or request.user.is_vice_rector):
            raise PermissionDenied(_('This section is for Department Heads only.'))
        return super().dispatch(request, *args, **kwargs)


class DeptHeadDashboardView(DeptHeadRequiredMixin, View):
    """Department Dashboard is removed in favor of unified Tasks & Execution navigation."""
    def get(self, request, *args, **kwargs):
        return redirect('task_list')


class DeptHeadTaskListView(DeptHeadRequiredMixin, ListView):
    template_name = 'workflow/dept_task_list.html'
    context_object_name = 'tasks'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = get_scoped_tasks(user).select_related(
            'responsible_department', 'creator', 'task_type'
        ).prefetch_related('assignments__user')

        # Filters
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        priority = self.request.GET.get('priority')
        if priority:
            qs = qs.filter(priority=priority)

        return qs.order_by('deadline', '-priority')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['task_statuses'] = Task.Status.choices
        ctx['task_priorities'] = Task.Priority.choices
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['current_priority'] = self.request.GET.get('priority', '')
        return ctx


class DeptHeadAssignEmployeesView(DeptHeadRequiredMixin, View):
    """POST: assign one or more employees to a task."""

    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        if not can_assign_employees_to_task(request.user, task):
            raise PermissionDenied(_('You cannot assign employees to this task.'))

        employee_ids = request.POST.getlist('employee_ids')
        if not employee_ids:
            messages.error(request, _('Please select at least one employee.'))
            return redirect('dept_task_list')

        # Only allow employees in the same department
        allowed_dept = task.responsible_department
        employees = User.objects.filter(
            id__in=employee_ids,
            department=allowed_dept,
            is_active=True,
        )
        if not employees.exists():
            messages.error(request, _('No valid employees selected.'))
            return redirect('dept_task_list')

        # Check for cross-department attempt
        if employees.count() != len(employee_ids):
            messages.warning(request, _('Some selected employees were excluded (wrong department or inactive).'))

        try:
            assign_task(request.user, task, list(employees), request=request)
            count = employees.count()
            messages.success(request, _(f'{count} employee(s) assigned to the task successfully.'))
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect('task_detail', pk=pk)


class DeptHeadTaskDetailView(DeptHeadRequiredMixin, View):
    """Department Head view of a task - seamlessly routes to comprehensive task detail."""

    def get(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        if not can_view_task(request.user, task):
            raise PermissionDenied(_('You do not have permission to view this task.'))
        return redirect('task_detail', pk=task.pk)


class DeptHeadFirstApprovalQueueView(DeptHeadRequiredMixin, ListView):
    template_name = 'workflow/dept_first_approval.html'
    context_object_name = 'submissions'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        dept = user.department

        qs = TaskSubmission.objects.filter(
            status=TaskSubmission.SubmissionStatus.PENDING_FIRST_APPROVAL
        ).exclude(
            task__status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]
        ).select_related(
            'task', 'task__responsible_department',
            'assignment', 'assignment__user', 'assignment__user__position',
            'submitted_by',
        )

        if dept and not user.is_rector:
            qs = qs.filter(task__responsible_department=dept)
        elif user.is_vice_rector:
            scoped_depts = user.get_scoped_departments()
            qs = qs.filter(task__responsible_department__in=scoped_depts)

        from core.middleware import get_current_active_year
        active_year = get_current_active_year()
        if active_year:
            qs = qs.filter(task__created_at__year=active_year)

        return qs.order_by('-submitted_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        page_subs = ctx.get('submissions', [])
        page_ids = [str(s.id) for s in page_subs]
        if page_ids and hasattr(self.request, 'session'):
            seen_apps = set(self.request.session.get('seen_first_approvals', []))
            seen_apps.update(page_ids)
            self.request.session['seen_first_approvals'] = list(seen_apps)
            self.request.session.modified = True
        return ctx


class DeptHeadSubmissionDetailView(DeptHeadRequiredMixin, DetailView):
    template_name = 'workflow/submission_detail.html'
    context_object_name = 'submission'

    def get_object(self):
        sub = get_object_or_404(
            TaskSubmission.objects.select_related(
                'task', 'task__responsible_department', 'task__creator',
                'assignment', 'assignment__user', 'assignment__user__position',
                'assignment__user__department', 'submitted_by',
            ),
            pk=self.kwargs['pk'],
        )
        if not can_view_submission(self.request.user, sub):
            raise PermissionDenied(_('You do not have permission to view this submission.'))
        return sub

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sub = self.object
        task = sub.task

        # Full task history for timeline
        ctx['history'] = task.history.select_related('actor').order_by('created_at')

        # All submissions for this assignment (versioning)
        ctx['all_submissions'] = TaskSubmission.objects.filter(
            assignment=sub.assignment
        ).order_by('-version')

        # Phase 6 — Evidence Files, Folders & Reports
        ctx['files'] = TaskFile.objects.filter(task=task, is_active=True).select_related('folder', 'uploaded_by').order_by('folder__name', '-created_at')
        ctx['folders'] = TaskFolder.objects.filter(task=task, is_active=True).order_by('name')
        ctx['reports'] = TaskReport.objects.filter(task=task).select_related('author').order_by('-created_at')

        ctx['task'] = task
        ctx['assignment'] = sub.assignment
        ctx['can_first_approve'] = can_first_approve_assignment(self.request.user, sub.assignment)
        ctx['can_first_reject'] = can_first_reject_assignment(self.request.user, sub.assignment)
        ctx['approval_phase_active'] = True
        ctx['work_notes'] = get_visible_task_notes(self.request.user, task)
        ctx['can_add_note'] = can_add_task_note(self.request.user, task)

        if hasattr(self.request, 'session'):
            seen_first = set(self.request.session.get('seen_first_approvals', []))
            seen_first.add(str(sub.id))
            if getattr(sub, 'task_id', None):
                seen_first.add(str(sub.task_id))
            self.request.session['seen_first_approvals'] = list(seen_first)
            self.request.session.modified = True

        return ctx


# ===========================================================================
# PHASE 5 — Department Head Approval Actions
# ===========================================================================

class DeptHeadApproveSubmissionView(DeptHeadRequiredMixin, View):
    """POST: Department Head approves submission and moves it to Second Approval."""

    def post(self, request, pk):
        sub = get_object_or_404(TaskSubmission.objects.select_related('assignment', 'task'), pk=pk)
        assignment = sub.assignment

        if not can_first_approve_assignment(request.user, assignment):
            raise PermissionDenied(_('You do not have permission to approve this submission.'))

        notes = request.POST.get('notes', '').strip()
        try:
            first_approve_assignment(request.user, assignment, notes=notes, request=request)
            messages.success(
                request,
                _('Submission for task {task_num} was approved and forwarded for management second approval.').format(
                    task_num=assignment.task.task_number
                ),
            )
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect('dept_first_approval')


class DeptHeadRejectSubmissionView(DeptHeadRequiredMixin, View):
    """POST: Department Head rejects submission with a required reason."""

    def post(self, request, pk):
        sub = get_object_or_404(TaskSubmission.objects.select_related('assignment', 'task'), pk=pk)
        assignment = sub.assignment

        if not can_first_reject_assignment(request.user, assignment):
            raise PermissionDenied(_('You do not have permission to reject this submission.'))

        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, _('Rejection reason is strictly required.'))
            return redirect('submission_detail', pk=pk)

        try:
            first_reject_assignment(request.user, assignment, reason=reason, request=request)
            messages.warning(
                request,
                _('Submission for task {task_num} was rejected.').format(
                    task_num=assignment.task.task_number
                ),
            )
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect('dept_first_approval')


# ===========================================================================
# PHASE 5 — Management Second & Final Approval Views
# ===========================================================================

class ManagementRequiredMixin(WorkflowLoginMixin):
    """View mixin requiring Superadmin, Rector or Vice Rector role."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_superuser or request.user.can_act_as_rector or request.user.is_vice_rector):
            raise PermissionDenied(_('Access restricted to university leadership (Superadmin / Rector / Vice Rector).'))
        return super().dispatch(request, *args, **kwargs)


class ManagementSecondApprovalDashboardView(ManagementRequiredMixin, ListView):
    """Management dashboard listing tasks awaiting signature / second approval and signed tasks."""
    template_name = 'workflow/management_second_approval.html'
    context_object_name = 'assignments'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        tab = self.request.GET.get('tab', 'pending')

        base_qs = (
            TaskAssignment.objects
            .exclude(task__status__in=[Task.Status.CANCELLED, Task.Status.ARCHIVED])
            .select_related(
                'task', 'task__responsible_department', 'task__creator',
                'user', 'user__position', 'assigned_by',
            )
            .prefetch_related('task__signatures')
        )

        if user.is_vice_rector and not (user.can_act_as_rector or user.is_superuser):
            scoped_depts = user.get_scoped_departments()
            base_qs = base_qs.filter(
                Q(task__responsible_department__in=scoped_depts)
                | Q(task__secondary_departments__in=scoped_depts)
                | Q(user__department__in=scoped_depts)
            )

        if tab == 'signed':
            qs = base_qs.filter(task__signatures__status='SIGNED').distinct()
        else:
            # Pending: tasks awaiting signature / second approval
            pending_qs = base_qs.filter(
                Q(assignment_status__in=[
                    TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                    TaskAssignment.AssignmentStatus.SUBMITTED,
                ])
                | Q(task__status=Task.Status.COMPLETED)
            ).exclude(
                task__signatures__status='SIGNED'
            )

            # --- One row per task ---
            # For each task pick the single "primary" assignment:
            # priority: SECOND_APPROVAL (0) > SUBMITTED (1) > other (2), then earliest created.
            # This ensures the employee's work assignment is shown, not the dept-head approval record.
            primary_pk_subq = (
                TaskAssignment.objects
                .filter(task_id=OuterRef('task_id'))
                .filter(
                    Q(assignment_status__in=[
                        TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                        TaskAssignment.AssignmentStatus.SUBMITTED,
                    ])
                    | Q(task__status=Task.Status.COMPLETED)
                )
                .exclude(task__signatures__status='SIGNED')
                .annotate(
                    status_priority=Case(
                        When(assignment_status=TaskAssignment.AssignmentStatus.SECOND_APPROVAL, then=Value(0)),
                        When(assignment_status=TaskAssignment.AssignmentStatus.SUBMITTED, then=Value(1)),
                        default=Value(2),
                        output_field=IntegerField(),
                    )
                )
                .order_by('status_priority', 'created_at')
                .values('pk')[:1]
            )
            qs = pending_qs.filter(pk=Subquery(primary_pk_subq))

        # Filters
        dept_id = self.request.GET.get('department')
        if dept_id:
            qs = qs.filter(task__responsible_department_id=dept_id)

        priority = self.request.GET.get('priority')
        if priority:
            qs = qs.filter(task__priority=priority)

        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(task__task_number__icontains=query)
                | Q(task__title__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )

        return qs.order_by('task__deadline', '-updated_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        tab = self.request.GET.get('tab', 'pending')

        if user.is_superuser or user.is_rector:
            ctx['departments'] = Department.objects.filter(is_active=True).order_by('name')
        else:
            ctx['departments'] = user.get_scoped_departments().filter(is_active=True).order_by('name')
        ctx['task_priorities'] = Task.Priority.choices
        ctx['selected_dept'] = self.request.GET.get('department', '')
        ctx['selected_priority'] = self.request.GET.get('priority', '')
        ctx['search_query'] = self.request.GET.get('q', '')

        # Tab counts
        count_base = TaskAssignment.objects.exclude(
            task__status__in=[Task.Status.CANCELLED, Task.Status.ARCHIVED]
        )
        if user.is_vice_rector and not (user.is_rector or user.is_superuser):
            scoped_depts = user.get_scoped_departments()
            count_base = count_base.filter(task__responsible_department__in=scoped_depts)

        ctx['pending_count'] = count_base.filter(
            Q(assignment_status__in=[
                TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                TaskAssignment.AssignmentStatus.SUBMITTED,
            ])
            | Q(task__status=Task.Status.COMPLETED)
        ).exclude(task__signatures__status='SIGNED').values('task_id').distinct().count()

        ctx['signed_count'] = count_base.filter(
            task__signatures__status='SIGNED'
        ).values('task_id').distinct().count()

        ctx['active_tab'] = tab
        query_dict = self.request.GET.copy()
        query_dict.pop('page', None)
        ctx['filter_params'] = query_dict.urlencode()

        # Mark displayed pending approval tasks as seen in session so the badge updates
        if tab != 'signed':
            page_assignments = ctx.get('assignments', [])
            page_ids = []
            for a in page_assignments:
                page_ids.append(str(a.id))
                if getattr(a, 'task_id', None):
                    page_ids.append(str(a.task_id))
            if page_ids and hasattr(self.request, 'session'):
                seen_second = set(self.request.session.get('seen_second_approvals', []))
                seen_second.update(page_ids)
                self.request.session['seen_second_approvals'] = list(seen_second)
                self.request.session.modified = True

        return ctx


class ManagementSecondApprovalDetailView(ManagementRequiredMixin, DetailView):
    """Management review page for a task awaiting second approval or review/signing."""
    template_name = 'workflow/management_second_approval_detail.html'
    context_object_name = 'assignment'

    def get_object(self):
        assignment = get_object_or_404(
            TaskAssignment.objects.select_related(
                'task', 'task__responsible_department', 'task__creator',
                'user', 'user__position', 'user__department', 'assigned_by',
            ),
            pk=self.kwargs['pk'],
        )
        user = self.request.user
        if not (user.is_superuser or user.can_act_as_rector or user.is_vice_rector):
            raise PermissionDenied(_('Access restricted to university leadership (Superadmin / Rector / Vice Rector).'))
        if user.is_vice_rector and not (user.is_superuser or user.can_act_as_rector):
            dept_id = assignment.task.responsible_department_id
            scoped = user.get_scoped_departments()
            in_scope = (
                (dept_id and scoped.filter(id=dept_id).exists())
                or (assignment.user.department_id and scoped.filter(id=assignment.user.department_id).exists())
                or assignment.task.secondary_departments.filter(id__in=scoped.values_list('id', flat=True)).exists()
            )
            if not in_scope:
                raise PermissionDenied(_('This task is outside your supervised department scope.'))
        return assignment

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        assignment = self.object
        task = assignment.task

        ctx['task'] = task
        ctx['latest_submission'] = (
            TaskSubmission.objects
            .filter(assignment=assignment)
            .order_by('-version')
            .first()
        )
        ctx['all_submissions'] = (
            TaskSubmission.objects
            .filter(assignment=assignment)
            .order_by('-version')
        )
        ctx['work_notes'] = get_visible_task_notes(self.request.user, task)
        ctx['can_add_note'] = can_add_task_note(self.request.user, task)
        ctx['approvals'] = (
            TaskApproval.objects
            .filter(task=task)
            .select_related('actor')
            .order_by('-created_at')
        )
        ctx['deadline_extensions'] = (
            TaskDeadlineExtension.objects
            .filter(task=task)
            .select_related('extended_by')
            .order_by('-created_at')
        )
        ctx['history'] = task.history.select_related('actor').order_by('created_at')

        # Phase 6 — Evidence Files, Folders & Reports
        ctx['files'] = TaskFile.objects.filter(task=task, is_active=True).select_related('folder', 'uploaded_by').order_by('folder__name', '-created_at')
        ctx['folders'] = TaskFolder.objects.filter(task=task, is_active=True).order_by('name')
        ctx['reports'] = TaskReport.objects.filter(task=task).select_related('author').order_by('-created_at')

        # Phase 9: Electronic Signature
        task_signature = task.signatures.filter(status='SIGNED').select_related('signer', 'signer__position').first()
        ctx['task_signature'] = task_signature
        if task_signature:
            from signatures.qr import generate_qr_data_uri
            ctx['signature_verification_url'] = self.request.build_absolute_uri(
                reverse('public_verify', kwargs={'verification_id': task_signature.verification_id})
            )
            ctx['signature_qr_data_uri'] = generate_qr_data_uri(ctx['signature_verification_url'])

        # can_final_approve: Vice Rector can approve the workflow stage but CANNOT sign.
        # Signing is exclusively for Rector, Acting Rector, and Superadmin.
        user = self.request.user
        is_signer = user.can_act_as_rector or user.is_superuser
        is_approver = is_signer or user.is_vice_rector
        ctx['can_sign'] = is_signer and (not task_signature) and (
            task.status == Task.Status.COMPLETED or assignment.assignment_status in (
                TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                TaskAssignment.AssignmentStatus.SUBMITTED,
            )
        )
        ctx['can_final_approve'] = is_approver and (not task_signature) and (
            task.status == Task.Status.COMPLETED or assignment.assignment_status in (
                TaskAssignment.AssignmentStatus.SECOND_APPROVAL,
                TaskAssignment.AssignmentStatus.SUBMITTED,
            )
        )
        ctx['can_reject'] = can_second_reject_assignment(self.request.user, assignment) and not task_signature
        ctx['can_extend_deadline'] = can_extend_task_deadline(self.request.user, task)

        # Mark this task as seen
        if hasattr(self.request, 'session'):
            seen_second = set(self.request.session.get('seen_second_approvals', []))
            seen_second.add(str(assignment.id))
            if getattr(assignment, 'task_id', None):
                seen_second.add(str(assignment.task_id))
            self.request.session['seen_second_approvals'] = list(seen_second)
            self.request.session.modified = True

        return ctx


class ManagementFinalApproveView(ManagementRequiredMixin, View):
    """POST: Management grants final approval and electronically signs the task with QR-coded PDF."""

    def post(self, request, pk):
        assignment = get_object_or_404(
            TaskAssignment.objects.select_related('task'), pk=pk
        )
        user = request.user
        task = assignment.task

        if user.is_vice_rector and not (user.is_superuser or user.can_act_as_rector):
            dept_id = task.responsible_department_id
            scoped = user.get_scoped_departments()
            in_scope = (
                (dept_id and scoped.filter(id=dept_id).exists())
                or (assignment.user.department_id and scoped.filter(id=assignment.user.department_id).exists())
                or task.secondary_departments.filter(id__in=scoped.values_list('id', flat=True)).exists()
            )
            if not in_scope:
                raise PermissionDenied(_('You do not have permission to grant final approval on this task.'))

        notes = request.POST.get('notes', '').strip()
        try:
            # 1. Final approve if not yet completed
            if task.status != Task.Status.COMPLETED:
                final_approve_assignment(user, assignment, notes=notes, request=request)
                task.refresh_from_db()

            # 2. Digitally sign with Ed25519 and generate signed PDF with QR code
            # Only Rector (or Acting Rector) and Superadmin may electronically sign.
            is_signed = task.signatures.filter(status='SIGNED').exists()
            if not is_signed and (user.can_act_as_rector or user.is_superuser):
                from signatures.services import sign_task
                signature = sign_task(task=task, signer=user, request=request)
                messages.success(
                    request,
                    _('Task {task_num} has been successfully approved and electronically signed! Verification ID: {ver_id}').format(
                        task_num=task.task_number,
                        ver_id=signature.verification_id,
                    ),
                )
            else:
                messages.success(
                    request,
                    _('Task {task_num} has been successfully completed and finally approved!').format(
                        task_num=task.task_number
                    ),
                )
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            messages.error(request, _('An error occurred during final approval and electronic signing.'))

        return redirect('management_second_approval_detail', pk=assignment.pk)



class ManagementRejectView(ManagementRequiredMixin, View):
    """POST: Management rejects task at second approval with required reason."""

    def post(self, request, pk):
        assignment = get_object_or_404(
            TaskAssignment.objects.select_related('task'), pk=pk
        )
        if not can_second_reject_assignment(request.user, assignment):
            raise PermissionDenied(_('You do not have permission to reject this task.'))

        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, _('Rejection reason is strictly required.'))
            return redirect('management_second_approval_detail', pk=pk)

        try:
            final_reject_assignment(request.user, assignment, reason=reason, request=request)
            messages.warning(
                request,
                _('Task {task_num} was rejected during second approval.').format(
                    task_num=assignment.task.task_number
                ),
            )
        except ValidationError as e:
            messages.error(request, str(e.message))

        return redirect('management_second_approval')


class TaskDeadlineExtensionView(ManagementRequiredMixin, View):
    """POST: Management extends the official deadline of a task."""

    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        if not can_extend_task_deadline(request.user, task):
            raise PermissionDenied(_('You do not have permission to extend the deadline for this task.'))

        new_deadline_str = request.POST.get('new_deadline', '').strip()
        reason = request.POST.get('reason', '').strip()

        if not new_deadline_str or not reason:
            messages.error(request, _('Both new deadline date and extension reason are strictly required.'))
            return redirect(request.META.get('HTTP_REFERER', 'management_second_approval'))

        from datetime import datetime
        try:
            new_deadline = datetime.strptime(new_deadline_str, '%Y-%m-%d').date()
            extend_task_deadline(request.user, task, new_deadline, reason, request=request)
            messages.success(
                request,
                _('Deadline for {task_num} successfully extended to {new_date}.').format(
                    task_num=task.task_number,
                    new_date=new_deadline,
                ),
            )
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))

        return redirect(request.META.get('HTTP_REFERER', 'management_second_approval'))


# ===========================================================================
# PHASE 5 — Completed & Rejected Views
# ===========================================================================

class SuccessfullyCompletedTasksView(WorkflowLoginMixin, ListView):
    """Scoped list of successfully completed tasks."""
    template_name = 'workflow/completed_tasks.html'
    context_object_name = 'tasks'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = get_scoped_tasks(user).filter(
            status=Task.Status.COMPLETED
        ).select_related(
            'responsible_department', 'creator', 'task_type'
        ).prefetch_related(
            'assignments__user', 'approvals__actor', 'deadline_extensions'
        )

        dept_id = self.request.GET.get('department')
        if dept_id:
            qs = qs.filter(responsible_department_id=dept_id)

        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(task_number__icontains=query)
                | Q(title__icontains=query)
                | Q(assignments__user__first_name__icontains=query)
                | Q(assignments__user__last_name__icontains=query)
            ).distinct()

        return qs.order_by('-completed_at', '-updated_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        if user.is_rector:
            ctx['departments'] = Department.objects.filter(is_active=True).order_by('name')
        elif user.is_vice_rector:
            ctx['departments'] = user.get_scoped_departments().filter(is_active=True).order_by('name')
        ctx['selected_dept'] = self.request.GET.get('department', '')
        ctx['search_query'] = self.request.GET.get('q', '')

        get_params = self.request.GET.copy()
        if 'page' in get_params:
            del get_params['page']
        ctx['filter_params'] = get_params.urlencode()
        return ctx


class RejectedTasksView(WorkflowLoginMixin, ListView):
    """Scoped list of rejected tasks."""
    template_name = 'workflow/rejected_tasks.html'
    context_object_name = 'approvals'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        scoped_tasks = get_scoped_tasks(user)

        qs = TaskApproval.objects.filter(
            decision=TaskApproval.Decision.REJECTED,
            task__in=scoped_tasks,
        ).select_related(
            'task', 'task__responsible_department', 'actor',
            'assignment', 'assignment__user', 'submission'
        )

        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(task__task_number__icontains=query)
                | Q(task__title__icontains=query)
                | Q(reason__icontains=query)
                | Q(actor__first_name__icontains=query)
                | Q(actor__last_name__icontains=query)
            )

        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['search_query'] = self.request.GET.get('q', '')

        get_params = self.request.GET.copy()
        if 'page' in get_params:
            del get_params['page']
        ctx['filter_params'] = get_params.urlencode()
        return ctx


class WorkflowApprovalsHubView(WorkflowLoginMixin, View):
    """
    Central smart router for Approvals:
    - Rector / Vice Rector / Superadmin -> Final Approval Center
    - Department Head -> Department Approvals
    - Employee -> Submitted tasks awaiting review
    """
    def get(self, request, *args, **kwargs):
        user = request.user
        if user.is_superuser or user.is_rector or user.is_vice_rector:
            return redirect('management_second_approval')
        elif user.is_department_head:
            return redirect('dept_first_approval')
        return redirect('employee_first_approval')


