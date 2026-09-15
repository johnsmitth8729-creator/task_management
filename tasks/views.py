from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from accounts.models import Role, User
from accounts.permissions import RectorRequiredMixin
from organization.models import Department
from tasks.forms import (
    SubTaskForm,
    TaskAssignForm,
    TaskCancelForm,
    TaskCreateForm,
    TaskDependencyForm,
    TaskFromTemplateForm,
    TaskTemplateForm,
    TaskTypeForm,
    TaskUpdateForm,
)
from tasks.models import (
    SubTask,
    Task,
    TaskAssignment,
    TaskDependency,
    TaskTemplate,
    TaskType,
)
from tasks.permissions import (
    TaskAccessMixin,
    TaskArchiveMixin,
    TaskAssignMixin,
    TaskCancelMixin,
    TaskCreateRequiredMixin,
    TaskDeleteMixin,
    TaskEditMixin,
    can_add_task_note,
    can_archive_task,
    can_assign_task,
    can_cancel_task,
    can_create_task,
    can_delete_task,
    can_edit_task,
    can_manage_dependencies,
    can_manage_subtasks,
    can_manage_task_types,
    can_manage_templates,
    can_unassign_user,
    is_task_in_submission_or_approval,
)
from tasks.services import (
    add_dependency,
    add_task_note,
    archive_task,
    assign_task,
    cancel_task,
    create_subtask,
    create_task,
    get_scoped_tasks,
    get_visible_task_notes,
    remove_dependency,
    transition_status,
    unassign_user,
    update_task,
)


class TaskListView(LoginRequiredMixin, ListView):
    model = Task
    template_name = 'tasks/task_list.html'
    context_object_name = 'tasks'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        include_archived = self.request.GET.get('include_archived') == '1'
        qs = get_scoped_tasks(user, include_archived=include_archived).select_related(
            'responsible_department', 'task_type', 'creator'
        ).prefetch_related('assignments__user')

        # Filters
        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(task_number__icontains=query)
                | Q(title__icontains=query)
                | Q(description__icontains=query)
            )

        dept_id = self.request.GET.get('department', '').strip()
        if dept_id:
            qs = qs.filter(responsible_department_id=dept_id)

        task_type_id = self.request.GET.get('task_type', '').strip()
        if task_type_id:
            qs = qs.filter(task_type_id=task_type_id)

        priority = self.request.GET.get('priority', '').strip()
        if priority:
            qs = qs.filter(priority=priority)

        complexity = self.request.GET.get('complexity', '').strip()
        if complexity:
            qs = qs.filter(complexity=complexity)

        status = self.request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)

        assignee_id = self.request.GET.get('assignee', '').strip()
        if assignee_id:
            qs = qs.filter(assignments__user_id=assignee_id)

        is_overdue = self.request.GET.get('is_overdue', '').strip()
        if is_overdue == '1':
            qs = qs.filter(
                deadline__lt=timezone.now().date()
            ).exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])

        # Scope filter (control / incoming / in_progress)
        scope = self.request.GET.get('scope', '').strip()
        if scope == 'control':
            qs = qs.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED])
            if user.is_superuser or user.is_rector:
                qs = qs.filter(Q(creator=user) | Q(status__in=[Task.Status.ASSIGNED, Task.Status.IN_PROGRESS]))
            elif user.is_vice_rector:
                scoped_depts = user.get_scoped_departments()
                qs = qs.filter(Q(creator=user) | Q(responsible_department__in=scoped_depts))
            elif user.is_department_head and user.department_id:
                qs = qs.filter(Q(creator=user) | Q(responsible_department_id=user.department_id))
            else:
                qs = qs.filter(creator=user)
        elif scope == 'incoming':
            qs = qs.filter(
                assignments__user=user,
                assignments__assignment_status=TaskAssignment.AssignmentStatus.ASSIGNED
            )
        elif scope == 'in_progress':
            qs = qs.filter(
                assignments__user=user,
                assignments__assignment_status=TaskAssignment.AssignmentStatus.IN_PROGRESS
            )

        # Year filter (defaults to session active_year unless 'all' is explicitly requested)
        year_param = self.request.GET.get('year', '').strip()
        if year_param == 'all':
            pass
        elif year_param.isdigit():
            qs = qs.filter(created_at__year=int(year_param))
        else:
            active_year = self.request.session.get('active_year')
            if active_year:
                try:
                    qs = qs.filter(created_at__year=int(active_year))
                except (ValueError, TypeError):
                    pass

        # Sorting
        sort = self.request.GET.get('sort', '-created_at')
        allowed_sorts = {
            'created_at': 'created_at',
            '-created_at': '-created_at',
            'deadline': 'deadline',
            '-deadline': '-deadline',
            'priority': 'priority',
            '-priority': '-priority',
            'progress': 'progress',
            '-progress': '-progress',
            'updated_at': '-updated_at',
        }
        order_field = allowed_sorts.get(sort, '-created_at')
        return qs.order_by(order_field)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['can_create_task'] = can_create_task(user)
        context['priorities'] = Task.Priority.choices
        context['complexities'] = Task.Complexity.choices
        if self.request.GET.get('scope', '').strip() == 'control':
            context['statuses'] = [
                c for c in Task.Status.choices
                if c[0] not in [Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]
            ]
        else:
            context['statuses'] = Task.Status.choices
        context['task_types'] = TaskType.objects.filter(is_active=True).order_by('name')

        if user.is_rector:
            context['departments'] = Department.objects.filter(is_active=True).order_by('name')
        elif user.is_vice_rector:
            context['departments'] = user.get_scoped_departments().filter(is_active=True).order_by('name')
        else:
            context['departments'] = Department.objects.filter(id=user.department_id) if user.department_id else []

        # Current filters
        context['selected_q'] = self.request.GET.get('q', '')
        context['selected_department'] = self.request.GET.get('department', '')
        context['selected_task_type'] = self.request.GET.get('task_type', '')
        context['selected_priority'] = self.request.GET.get('priority', '')
        context['selected_complexity'] = self.request.GET.get('complexity', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_assignee'] = self.request.GET.get('assignee', '')
        context['selected_is_overdue'] = self.request.GET.get('is_overdue', '')
        context['selected_scope'] = self.request.GET.get('scope', '')
        context['selected_sort'] = self.request.GET.get('sort', '-created_at')
        context['include_archived'] = self.request.GET.get('include_archived', '')

        # Build clean query string for numbered pagination preserving all active filters except 'page'
        get_params = self.request.GET.copy()
        if 'page' in get_params:
            del get_params['page']
        context['filter_params'] = get_params.urlencode()

        # Mark displayed tasks as seen in session so unread/action badges update
        scope = self.request.GET.get('scope', '').strip()
        is_overdue = self.request.GET.get('is_overdue', '').strip()
        page_tasks = context.get('tasks', [])
        page_ids = [str(t.id) for t in page_tasks]

        if page_ids and hasattr(self.request, 'session'):
            if scope == 'control':
                seen_ctrl = set(self.request.session.get('seen_control_tasks', []))
                seen_ctrl.update(page_ids)
                self.request.session['seen_control_tasks'] = list(seen_ctrl)
                self.request.session.modified = True
            if is_overdue == '1':
                seen_od = set(self.request.session.get('seen_overdue_tasks', []))
                seen_od.update(page_ids)
                self.request.session['seen_overdue_tasks'] = list(seen_od)
                self.request.session.modified = True

        return context


class TaskDetailView(TaskAccessMixin, DetailView):
    model = Task
    template_name = 'tasks/task_detail.html'
    context_object_name = 'task'

    def get_queryset(self):
        return Task.objects.select_related(
            'responsible_department', 'task_type', 'creator', 'cancelled_by'
        ).prefetch_related(
            'assignments__user__position',
            'subtasks__assignee',
            'dependencies__depends_on',
            'dependents__task',
            'history__actor',
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        # Mark individual viewed task in session for unread badge decrements
        task_id = str(self.object.id)
        if hasattr(request, 'session'):
            seen_ctrl = set(request.session.get('seen_control_tasks', []))
            seen_ctrl.add(task_id)
            request.session['seen_control_tasks'] = list(seen_ctrl)

            seen_od = set(request.session.get('seen_overdue_tasks', []))
            seen_od.add(task_id)
            request.session['seen_overdue_tasks'] = list(seen_od)
            request.session.modified = True

        # Dynamic Routing: Route assigned employees and primary assignee to Employee Work Area (Image 1)
        if request.GET.get('view') != 'manage':
            assignment = self.object.assignments.filter(user=user).first()
            if assignment:
                is_rector_or_super = user.is_superuser or user.can_act_as_rector
                is_creator = (self.object.creator_id == user.id)
                is_assigner = self.object.assignments.filter(assigned_by=user).exclude(user=user).exists()

                # If user did not assign subordinates and is not executive leadership or creator,
                # they are an assigned employee / primary assignee -> open Image 1 (assignment_detail)
                if not (is_rector_or_super or is_creator or is_assigner):
                    return redirect('assignment_detail', pk=assignment.pk)

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        task = self.object
        user = self.request.user

        context['user_assignment'] = task.assignments.filter(user=user).first()
        context['can_edit'] = can_edit_task(user, task)
        context['can_delete'] = can_delete_task(user, task)
        context['can_cancel'] = can_cancel_task(user, task)
        context['can_archive'] = can_archive_task(user, task)
        context['can_assign'] = can_assign_task(user, task)
        context['can_manage_subtasks'] = can_manage_subtasks(user, task)
        context['can_manage_dependencies'] = can_manage_dependencies(user, task)

        # Forms for modal dialogs / inline creation
        if context['can_manage_subtasks']:
            context['subtask_form'] = SubTaskForm(task=task)
        if context['can_manage_dependencies']:
            context['dependency_form'] = TaskDependencyForm(task=task, user=user)

        context['subtasks'] = task.subtasks.all().select_related('assignee').order_by('created_at')
        context['dependencies'] = task.dependencies.all().select_related('depends_on')
        context['dependents'] = task.dependents.all().select_related('task')
        context['history_events'] = task.history.all().select_related('actor')[:30]

        # Phase 4 — Employee & Management Work Notes
        context['work_notes'] = get_visible_task_notes(user, task)
        context['can_add_note'] = can_add_task_note(user, task)

        # Assigned employees with per-assignment unassign permission
        context['is_task_submitted_or_review'] = is_task_in_submission_or_approval(task)
        assignments = list(task.assignments.select_related('user', 'user__position', 'assigned_by').all())
        for a in assignments:
            a.can_unassign = can_unassign_user(user, task, a)
        context['task_assignments'] = assignments

        # Phase 6 — Work Evidence Files, Folders & Reports
        from files.forms import TaskFileUploadForm, TaskFolderForm
        from files.models import TaskFile, TaskFolder, TaskReport
        from files.permissions import (
            can_create_report,
            can_manage_folders,
            can_upload_task_file,
        )

        context['files'] = TaskFile.objects.filter(task=task, is_active=True).select_related('folder', 'uploaded_by').order_by('folder__name', '-created_at')
        context['folders'] = TaskFolder.objects.filter(task=task, is_active=True).order_by('name')
        context['reports'] = TaskReport.objects.filter(task=task).select_related('author').order_by('-created_at')
        context['can_upload_file'] = can_upload_task_file(user, task)
        context['can_manage_folders'] = can_manage_folders(user, task)
        context['can_create_report'] = can_create_report(user, task)
        context['file_upload_form'] = TaskFileUploadForm(task=task)
        context['folder_form'] = TaskFolderForm(task=task)

        # Phase 9 — Electronic Signature & Verification
        from signatures.models import ElectronicSignature
        from signatures.permissions import can_revoke_signature, can_sign_task
        from signatures.qr import generate_qr_data_uri

        active_sig = task.signatures.filter(status=ElectronicSignature.Status.SIGNED).select_related('signer', 'signer__position').first()
        latest_sig = active_sig or task.signatures.order_by('-signed_at').select_related('signer', 'signer__position').first()

        can_sign, sign_denial_reason = can_sign_task(user, task)
        context['task_signature'] = latest_sig
        context['can_sign_task'] = can_sign
        context['sign_denial_reason'] = sign_denial_reason
        context['can_revoke_signature'] = can_revoke_signature(user, latest_sig) if latest_sig else False

        if latest_sig:
            verification_url = self.request.build_absolute_uri(
                reverse('public_verify', kwargs={'verification_id': latest_sig.verification_id})
            )
            context['signature_verification_url'] = verification_url
            context['signature_qr_data_uri'] = generate_qr_data_uri(verification_url)

        return context


class TaskCreateView(TaskCreateRequiredMixin, FormView):
    template_name = 'tasks/task_form.html'
    form_class = TaskCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        assignees = form.cleaned_data.get('initial_assignees')
        primary = form.cleaned_data.get('primary_assignee')
        secondary_depts = form.cleaned_data.get('secondary_departments')
        try:
            task = create_task(
                actor=user,
                title=form.cleaned_data['title'],
                description=form.cleaned_data.get('description', ''),
                responsible_department=form.cleaned_data.get('responsible_department'),
                task_type=form.cleaned_data.get('task_type'),
                priority=form.cleaned_data.get('priority', Task.Priority.MEDIUM),
                complexity=form.cleaned_data.get('complexity', Task.Complexity.SIMPLE),
                start_date=form.cleaned_data.get('start_date'),
                deadline=form.cleaned_data.get('deadline'),
                initial_assignees=list(assignees) if assignees else None,
                primary_assignee=primary,
                secondary_departments=list(secondary_depts) if secondary_depts else None,
                request=self.request,
            )
            messages.success(self.request, _(f"Task {task.task_number} created successfully."))
            return redirect('task_detail', pk=task.pk)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = _('Create New Task')
        context['is_create'] = True

        import json
        form = context.get('form')
        assignees_qs = form.fields['initial_assignees'].queryset if (form and 'initial_assignees' in form.fields) else User.objects.none()
        employees_data = []
        for emp in assignees_qs.select_related('department', 'position'):
            employees_data.append({
                'id': str(emp.id),
                'username': emp.username,
                'name': emp.display_name,
                'department_id': str(emp.department_id) if emp.department_id else '',
                'department_name': emp.department.name if emp.department else '',
                'position_name': emp.position.name if emp.position else '',
                'photo_url': emp.photo.url if emp.photo else '',
                'initials': emp.initials,
            })
        context['employees_json'] = json.dumps(employees_data)
        return context


class TaskUpdateView(TaskEditMixin, FormView):
    template_name = 'tasks/task_form.html'
    form_class = TaskUpdateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['instance'] = self.get_task()
        return kwargs

    def get_initial(self):
        task = self.get_task()
        return {
            'title': task.title,
            'description': task.description,
            'responsible_department': task.responsible_department,
            'task_type': task.task_type,
            'priority': task.priority,
            'complexity': task.complexity,
            'progress': task.progress,
            'start_date': task.start_date,
            'deadline': task.deadline,
        }

    def form_valid(self, form):
        task = self.get_task()
        try:
            update_task(
                actor=self.request.user,
                task=task,
                data=form.cleaned_data,
                request=self.request,
            )
            messages.success(self.request, _(f"Task {task.task_number} updated successfully."))
            return redirect('task_detail', pk=task.pk)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['task'] = self.get_task()
        context['page_title'] = _(f"Edit Task: {self.get_task().task_number}")
        context['is_create'] = False
        return context


class TaskCancelView(TaskCancelMixin, FormView):
    template_name = 'tasks/task_cancel.html'
    form_class = TaskCancelForm

    def form_valid(self, form):
        task = self.get_task()
        reason = form.cleaned_data['cancellation_reason']
        try:
            cancel_task(
                actor=self.request.user,
                task=task,
                cancellation_reason=reason,
                request=self.request,
            )
            messages.warning(self.request, _(f"Task {task.task_number} has been cancelled."))
            return redirect('task_detail', pk=task.pk)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['task'] = self.get_task()
        return context


class TaskArchiveView(TaskArchiveMixin, View):
    def post(self, request, pk):
        task = self.get_task()
        try:
            archive_task(actor=request.user, task=task, request=request)
            messages.info(request, _(f"Task {task.task_number} has been archived."))
        except ValidationError as e:
            messages.error(request, e.message)
        return redirect('task_list')


class TaskDeleteView(TaskDeleteMixin, View):
    """Hard-delete a task. Only the creator may delete and only before work begins."""

    def post(self, request, pk):
        task = self.get_task()  # permission check happens in mixin
        task_number = task.task_number
        task.delete()
        messages.success(request, _(f"Task {task_number} has been permanently deleted."))
        return redirect('task_list')


class TaskStatusChangeView(TaskEditMixin, View):
    def post(self, request, pk):
        task = self.get_task()
        new_status = request.POST.get('status')
        if not new_status:
            messages.error(request, _('Status is required.'))
            return redirect('task_detail', pk=task.pk)
        try:
            transition_status(actor=request.user, task=task, new_status=new_status, request=request)
            messages.success(request, _(f"Task status changed to {task.get_status_display()}."))
        except ValidationError as e:
            messages.error(request, e.message)
        return redirect('task_detail', pk=task.pk)


class TaskAssignView(TaskAssignMixin, FormView):
    template_name = 'tasks/task_assign.html'
    form_class = TaskAssignForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['task'] = self.get_task()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        task = self.get_task()
        assignees = form.cleaned_data['assignees']
        primary = form.cleaned_data.get('primary_assignee')
        try:
            assign_task(
                actor=self.request.user,
                task=task,
                users=list(assignees),
                primary_user=primary,
                request=self.request,
            )
            messages.success(self.request, _(f"Assignments updated for {task.task_number}."))
            return redirect('task_detail', pk=task.pk)
        except ValidationError as e:
            form.add_error(None, e.message)
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        task = self.get_task()
        context['task'] = task

        import json
        form = context.get('form')
        assignees_qs = form.fields['assignees'].queryset if (form and 'assignees' in form.fields) else User.objects.none()
        employees_data = []
        for emp in assignees_qs.select_related('department', 'position'):
            employees_data.append({
                'id': str(emp.id),
                'username': emp.username,
                'name': emp.display_name,
                'department_id': str(emp.department_id) if emp.department_id else '',
                'department_name': emp.department.name if emp.department else '',
                'position_name': emp.position.name if emp.position else '',
                'photo_url': emp.photo.url if getattr(emp, 'photo', None) else '',
                'initials': emp.initials,
            })
        context['employees_json'] = json.dumps(employees_data)

        # Pre-selected assignees & primary from existing task assignments or form initial
        initial_assignees = form.initial.get('assignees') if form else None
        if initial_assignees is None:
            initial_assignees = list(task.assignments.values_list('user_id', flat=True))
        primary_id = form.initial.get('primary_assignee') if form else None
        if not primary_id:
            primary_id = task.assignments.filter(is_primary=True).values_list('user_id', flat=True).first()

        context['initial_assignee_ids_json'] = json.dumps([str(uid) for uid in initial_assignees])
        context['initial_primary_id_json'] = json.dumps(str(primary_id) if primary_id else '')
        return context


class TaskUnassignView(TaskAccessMixin, View):
    def post(self, request, pk, assignment_pk):
        task = get_object_or_404(Task, pk=pk)
        assignment = get_object_or_404(TaskAssignment, pk=assignment_pk, task=task)
        if not can_unassign_user(request.user, task, assignment):
            if assignment.user_id == request.user.id:
                raise PermissionDenied(_('Biriktirilgan xodim o‘zini vazifadan chiqara olmaydi.'))
            raise PermissionDenied(_('Sizda ushbu xodimni vazifadan chiqarish huquqi yo‘q.'))
        try:
            unassign_user(actor=request.user, task=task, assignment=assignment, request=request)
            messages.info(request, _(f"Employee unassigned from {task.task_number}."))
        except ValidationError as e:
            messages.error(request, str(e.message))
        return redirect('task_detail', pk=task.pk)


# ---------------------------------------------------------------------------
# SubTasks
# ---------------------------------------------------------------------------

class SubTaskCreateView(TaskAccessMixin, View):
    def post(self, request, pk):
        task = self.get_task()
        if not can_manage_subtasks(request.user, task):
            raise PermissionDenied(_('You cannot add subtasks to this task.'))

        form = SubTaskForm(request.POST, task=task)
        if form.is_valid():
            create_subtask(
                actor=request.user,
                task=task,
                title=form.cleaned_data['title'],
                description=form.cleaned_data.get('description', ''),
                status=form.cleaned_data.get('status', SubTask.Status.TODO),
                progress=form.cleaned_data.get('progress', 0),
                assignee=form.cleaned_data.get('assignee'),
                deadline=form.cleaned_data.get('deadline'),
                request=request,
            )
            messages.success(request, _('Subtask added successfully.'))
        else:
            messages.error(request, _('Failed to add subtask. Please check required fields.'))
        return redirect('task_detail', pk=task.pk)


class SubTaskUpdateView(TaskAccessMixin, View):
    def post(self, request, pk, st_pk):
        task = self.get_task()
        if not can_manage_subtasks(request.user, task):
            raise PermissionDenied(_('You cannot edit subtasks on this task.'))

        subtask = get_object_or_404(SubTask, pk=st_pk, parent_task=task)
        new_status = request.POST.get('status')
        new_progress = request.POST.get('progress')

        if new_status:
            subtask.status = new_status
        if new_progress is not None:
            subtask.progress = max(0, min(100, int(new_progress)))
            if subtask.progress == 100:
                subtask.status = SubTask.Status.DONE

        subtask.save()
        messages.success(request, _('Subtask updated.'))
        return redirect('task_detail', pk=task.pk)


class SubTaskDeleteView(TaskAccessMixin, View):
    def post(self, request, pk, st_pk):
        task = self.get_task()
        if not can_manage_subtasks(request.user, task):
            raise PermissionDenied(_('You cannot delete subtasks on this task.'))

        subtask = get_object_or_404(SubTask, pk=st_pk, parent_task=task)
        subtask.delete()
        messages.info(request, _('Subtask removed.'))
        return redirect('task_detail', pk=task.pk)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

class DependencyAddView(TaskAccessMixin, View):
    def post(self, request, pk):
        task = self.get_task()
        if not can_manage_dependencies(request.user, task):
            raise PermissionDenied(_('You cannot manage dependencies on this task.'))

        depends_on_id = request.POST.get('depends_on')
        dep_type = request.POST.get('dependency_type', TaskDependency.DependencyType.FINISH_TO_START)

        if not depends_on_id:
            messages.error(request, _('Please select a task.'))
            return redirect('task_detail', pk=task.pk)

        depends_on = get_object_or_404(Task, pk=depends_on_id)
        try:
            add_dependency(
                actor=request.user,
                task=task,
                depends_on=depends_on,
                dependency_type=dep_type,
                request=request,
            )
            messages.success(request, _(f"Dependency on {depends_on.task_number} added."))
        except ValidationError as e:
            messages.error(request, e.message)
        return redirect('task_detail', pk=task.pk)


class DependencyRemoveView(TaskAccessMixin, View):
    def post(self, request, pk, dep_pk):
        task = self.get_task()
        if not can_manage_dependencies(request.user, task):
            raise PermissionDenied(_('You cannot manage dependencies on this task.'))

        dep = get_object_or_404(TaskDependency, pk=dep_pk, task=task)
        remove_dependency(actor=request.user, dependency=dep, request=request)
        messages.info(request, _('Dependency removed.'))
        return redirect('task_detail', pk=task.pk)


# ---------------------------------------------------------------------------
# Task Types (Rector Only)
# ---------------------------------------------------------------------------

class TaskTypeListView(RectorRequiredMixin, ListView):
    model = TaskType
    template_name = 'tasks/task_type_list.html'
    context_object_name = 'task_types'


class TaskTypeCreateView(RectorRequiredMixin, CreateView):
    model = TaskType
    form_class = TaskTypeForm
    template_name = 'tasks/task_type_form.html'
    success_url = reverse_lazy('task_type_list')

    def form_valid(self, form):
        messages.success(self.request, _('Task type created successfully.'))
        return super().form_valid(form)


class TaskTypeUpdateView(RectorRequiredMixin, UpdateView):
    model = TaskType
    form_class = TaskTypeForm
    template_name = 'tasks/task_type_form.html'
    success_url = reverse_lazy('task_type_list')

    def form_valid(self, form):
        messages.success(self.request, _('Task type updated successfully.'))
        return super().form_valid(form)


class TaskTypeToggleView(RectorRequiredMixin, View):
    def post(self, request, pk):
        tt = get_object_or_404(TaskType, pk=pk)
        tt.is_active = not tt.is_active
        tt.save(update_fields=['is_active'])
        status_str = _('activated') if tt.is_active else _('deactivated')
        messages.info(request, _(f"Task type '{tt.name}' has been {status_str}."))
        return redirect('task_type_list')


# ---------------------------------------------------------------------------
# Task Templates
# ---------------------------------------------------------------------------

class TaskTemplateListView(LoginRequiredMixin, ListView):
    model = TaskTemplate
    template_name = 'tasks/template_list.html'
    context_object_name = 'templates'

    def get_queryset(self):
        return TaskTemplate.objects.filter(is_active=True).select_related('task_type', 'created_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_manage'] = can_manage_templates(self.request.user)
        return context


class TaskTemplateCreateView(LoginRequiredMixin, CreateView):
    model = TaskTemplate
    form_class = TaskTemplateForm
    template_name = 'tasks/template_form.html'
    success_url = reverse_lazy('task_template_list')

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_templates(request.user):
            raise PermissionDenied(_('You do not have permission to manage task templates.'))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, _('Task template created successfully.'))
        return super().form_valid(form)


class TaskTemplateUpdateView(LoginRequiredMixin, UpdateView):
    model = TaskTemplate
    form_class = TaskTemplateForm
    template_name = 'tasks/template_form.html'
    success_url = reverse_lazy('task_template_list')

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_templates(request.user):
            raise PermissionDenied(_('You do not have permission to manage task templates.'))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, _('Task template updated successfully.'))
        return super().form_valid(form)


class TaskTemplateUseView(TaskCreateRequiredMixin, FormView):
    template_name = 'tasks/template_use.html'
    form_class = TaskFromTemplateForm

    def get_template_obj(self):
        return get_object_or_404(TaskTemplate, pk=self.kwargs['pk'], is_active=True)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['template'] = self.get_template_obj()
        return kwargs

    def form_valid(self, form):
        template = self.get_template_obj()
        deadline = form.cleaned_data.get('deadline')
        if not deadline and template.default_duration_days:
            deadline = timezone.now().date() + timedelta(days=template.default_duration_days)

        task = create_task(
            actor=self.request.user,
            title=form.cleaned_data['title'],
            description=template.description,
            responsible_department=form.cleaned_data['responsible_department'],
            task_type=template.task_type,
            priority=template.default_priority,
            complexity=template.default_complexity,
            start_date=timezone.now().date(),
            deadline=deadline,
            request=self.request,
        )
        messages.success(self.request, _(f"Task {task.task_number} created from template '{template.name}'."))
        return redirect('task_detail', pk=task.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['template'] = self.get_template_obj()
        return context


class TaskAddNoteView(TaskAccessMixin, View):
    """Allow authorized users (rector, vice rector, dept head, assignees) to add a work note to a task."""

    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        if not can_add_task_note(request.user, task):
            raise PermissionDenied(_('You do not have permission to add notes to this task.'))

        content = request.POST.get('content', '').strip()
        visibility = request.POST.get('visibility')

        # If the author is assigned to this task, link assignment
        assignment = task.assignments.filter(user=request.user).first()

        try:
            add_task_note(
                actor=request.user,
                task=task,
                content=content,
                assignment=assignment,
                request=request,
                visibility=visibility,
            )
            messages.success(request, _('Note added successfully.'))
        except ValidationError as e:
            messages.error(request, str(e.message))

        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('task_detail', pk=task.pk)

