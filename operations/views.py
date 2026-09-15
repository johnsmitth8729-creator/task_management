from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from accounts.models import Role
from operations.forms import (
    DocumentVersionForm,
    RequestApprovalDecisionForm,
    UniversityDocumentForm,
    UniversityRequestForm,
)
from operations.models import (
    DocumentVersion,
    RequestApprovalStep,
    RequestCategory,
    RequestType,
    UniversityDocument,
    UniversityRequest,
)
from operations.services import (
    DocumentService,
    RequestWorkflowEngine,
)


class ServiceCatalogView(LoginRequiredMixin, ListView):
    model = RequestCategory
    template_name = 'operations/service_catalog.html'
    context_object_name = 'categories'

    def get_queryset(self):
        return RequestCategory.objects.filter(is_active=True).prefetch_related(
            'request_types'
        ).order_by('display_order', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get('q', '').strip()
        if query:
            context['search_results'] = RequestType.objects.filter(
                Q(name__icontains=query) | Q(description__icontains=query),
                is_active=True
            ).select_related('category')
        context['search_query'] = query
        context['my_pending_requests_count'] = UniversityRequest.objects.filter(
            requester=self.request.user,
            status__in=[UniversityRequest.Status.SUBMITTED, UniversityRequest.Status.IN_REVIEW]
        ).count()
        return context


class RequestSubmitView(LoginRequiredMixin, View):
    template_name = 'operations/request_form.html'

    def get(self, request, type_id=None):
        request_type = None
        if type_id:
            request_type = get_object_or_404(RequestType, id=type_id, is_active=True)
        form = UniversityRequestForm(initial={'request_type': request_type})
        return render(request, self.template_name, {
            'form': form,
            'request_type': request_type,
        })

    def post(self, request, type_id=None):
        form = UniversityRequestForm(request.POST)
        if form.is_valid():
            req_type = form.cleaned_data['request_type']
            subject = form.cleaned_data['subject']
            is_urgent = form.cleaned_data['is_urgent']

            # Extract dynamic form inputs from POST
            details = {}
            for field in req_type.form_schema:
                fname = field.get('name')
                if fname in request.POST:
                    details[fname] = request.POST.get(fname)

            uni_req = RequestWorkflowEngine.submit_request(
                request_type=req_type,
                requester=request.user,
                subject=subject,
                details_payload=details,
                is_urgent=is_urgent,
            )
            messages.success(request, _('Request %s submitted successfully.') % uni_req.request_number)
            return redirect('operations:request_detail', pk=uni_req.id)

        return render(request, self.template_name, {
            'form': form,
            'request_type': None,
        })


class MyRequestsListView(LoginRequiredMixin, ListView):
    model = UniversityRequest
    template_name = 'operations/my_requests.html'
    context_object_name = 'requests'
    paginate_by = 20

    def get_queryset(self):
        qs = UniversityRequest.objects.filter(requester=self.request.user).select_related(
            'request_type', 'department'
        ).order_by('-created_at')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_status'] = self.request.GET.get('status', '')
        return context


class RequestApprovalQueueView(LoginRequiredMixin, ListView):
    model = RequestApprovalStep
    template_name = 'operations/approval_queue.html'
    context_object_name = 'pending_steps'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = RequestApprovalStep.objects.filter(
            status=RequestApprovalStep.StepStatus.PENDING,
            request__status__in=[UniversityRequest.Status.SUBMITTED, UniversityRequest.Status.IN_REVIEW]
        ).select_related('request__request_type', 'request__requester', 'request__department')

        if user.is_superuser:
            return qs.order_by('-request__is_urgent', 'created_at')

        # Role-based filtering
        conditions = Q(assigned_approver=user)
        if user.is_rector:
            conditions |= Q(approver_role=RequestApprovalStep.ApproverRole.RECTOR)
        if user.is_vice_rector:
            conditions |= Q(approver_role=RequestApprovalStep.ApproverRole.VICE_RECTOR)
        if user.is_department_head:
            conditions |= Q(approver_role=RequestApprovalStep.ApproverRole.DEPARTMENT_HEAD, request__department=user.department)
        if user.is_hr:
            conditions |= Q(approver_role=RequestApprovalStep.ApproverRole.HR_MANAGER)
        if user.is_finance:
            conditions |= Q(approver_role=RequestApprovalStep.ApproverRole.FINANCE_DIRECTOR)

        return qs.filter(conditions).order_by('-request__is_urgent', 'created_at')


class RequestDetailView(LoginRequiredMixin, View):
    template_name = 'operations/request_detail.html'

    def get(self, request, pk):
        uni_req = get_object_or_404(
            UniversityRequest.objects.select_related('request_type', 'requester', 'department'),
            id=pk
        )
        # Check permissions: requester, assigned approvers, department head, rector, superadmin
        user = request.user
        steps = uni_req.approval_steps.all().select_related('assigned_approver', 'decided_by').order_by('step_number')

        can_view = (
            user == uni_req.requester
            or user.is_superuser
            or user.is_rector
            or (user.is_vice_rector and uni_req.department and user.department_responsibilities.filter(department=uni_req.department, is_active=True).exists())
            or (user.is_department_head and user.department == uni_req.department)
            or (user.is_hr and uni_req.request_type.requires_hr_approval)
            or (user.is_finance and uni_req.request_type.requires_finance_approval)
            or steps.filter(assigned_approver=user).exists()
        )
        if not can_view:
            return HttpResponseForbidden(_("You are not authorized to view this university request."))

        # Check if user can decide the current pending step
        pending_step = steps.filter(status=RequestApprovalStep.StepStatus.PENDING, step_number=uni_req.current_step_number).first()
        can_decide = False
        if pending_step:
            if user.is_superuser or pending_step.assigned_approver == user:
                can_decide = True
            elif pending_step.approver_role == RequestApprovalStep.ApproverRole.RECTOR and user.is_rector:
                can_decide = True
            elif pending_step.approver_role == RequestApprovalStep.ApproverRole.VICE_RECTOR and user.is_vice_rector:
                can_decide = True
            elif pending_step.approver_role == RequestApprovalStep.ApproverRole.DEPARTMENT_HEAD and user.is_department_head and user.department == uni_req.department:
                can_decide = True
            elif pending_step.approver_role == RequestApprovalStep.ApproverRole.HR_MANAGER and user.is_hr:
                can_decide = True
            elif pending_step.approver_role == RequestApprovalStep.ApproverRole.FINANCE_DIRECTOR and user.is_finance:
                can_decide = True

        form = RequestApprovalDecisionForm() if can_decide else None

        return render(request, self.template_name, {
            'req': uni_req,
            'steps': steps,
            'pending_step': pending_step,
            'can_decide': can_decide,
            'form': form,
        })

    def post(self, request, pk):
        uni_req = get_object_or_404(UniversityRequest, id=pk)
        steps = uni_req.approval_steps.all()
        pending_step = steps.filter(status=RequestApprovalStep.StepStatus.PENDING, step_number=uni_req.current_step_number).first()
        if not pending_step:
            messages.error(request, _('No pending step available for decision.'))
            return redirect('operations:request_detail', pk=pk)

        form = RequestApprovalDecisionForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            comments = form.cleaned_data['comments']
            RequestWorkflowEngine.process_approval_step(
                step=pending_step,
                user=request.user,
                decision=decision,
                comments=comments
            )
            messages.success(request, _('Decision recorded successfully.'))
            return redirect('operations:request_detail', pk=pk)

        return redirect('operations:request_detail', pk=pk)


class RequestCancelView(LoginRequiredMixin, View):
    def post(self, request, pk):
        uni_req = get_object_or_404(UniversityRequest, id=pk)
        if RequestWorkflowEngine.cancel_request(uni_req, request.user):
            messages.info(request, _('Request has been cancelled.'))
        else:
            messages.error(request, _('Request could not be cancelled.'))
        return redirect('operations:my_requests')


# ---------------------------------------------------------------------------
# University Documents & Rector Orders Registry
# ---------------------------------------------------------------------------

class DocumentListView(LoginRequiredMixin, ListView):
    model = UniversityDocument
    template_name = 'operations/document_list.html'
    context_object_name = 'documents'
    paginate_by = 25

    def get_queryset(self):
        qs = UniversityDocument.objects.select_related('department', 'created_by').order_by('-effective_date')

        # Scope by active working year
        from core.middleware import get_current_active_year
        active_year = get_current_active_year() or (self.request.session.get('active_year') if hasattr(self.request, 'session') else None)
        if active_year:
            try:
                ay = int(active_year)
                qs = qs.filter(Q(effective_date__year=ay) | Q(created_at__year=ay))
            except (ValueError, TypeError):
                pass

        doc_type = self.request.GET.get('doc_type')
        query = self.request.GET.get('q', '').strip()
        if doc_type:
            qs = qs.filter(document_type=doc_type)
        if query:
            qs = qs.filter(Q(title__icontains=query) | Q(doc_number__icontains=query) | Q(description__icontains=query))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['doc_types'] = UniversityDocument.DocumentType.choices
        context['current_type'] = self.request.GET.get('doc_type', '')
        context['search_query'] = self.request.GET.get('q', '')
        context['can_manage_docs'] = self.request.user.is_superuser or self.request.user.is_rector or self.request.user.is_vice_rector
        return context


class DocumentDetailView(LoginRequiredMixin, DetailView):
    model = UniversityDocument
    template_name = 'operations/document_detail.html'
    context_object_name = 'doc'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['versions'] = self.object.versions.select_related('uploaded_by').order_by('-version_number')
        context['version_form'] = DocumentVersionForm()
        context['can_manage_docs'] = self.request.user.is_superuser or self.request.user.is_rector or self.request.user.is_vice_rector
        return context


class DocumentCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = UniversityDocument
    form_class = UniversityDocumentForm
    template_name = 'operations/document_form.html'
    success_url = reverse_lazy('operations:document_list')

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.is_rector or user.is_vice_rector or user.is_hr)

    def form_valid(self, form):
        form.instance.created_by = self.request.user

        from core.middleware import get_current_active_year
        active_year = get_current_active_year() or (self.request.session.get('active_year') if hasattr(self.request, 'session') else None)
        if active_year and form.instance.effective_date:
            try:
                ay = int(active_year)
                if form.instance.effective_date.year != ay and ay != timezone.now().year:
                    form.instance.effective_date = form.instance.effective_date.replace(year=ay)
            except (ValueError, TypeError):
                pass

        messages.success(self.request, _('Document registered successfully.'))
        return super().form_valid(form)


class DocumentVersionUploadView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.is_rector or user.is_vice_rector or user.is_hr)

    def post(self, request, pk):
        doc = get_object_or_404(UniversityDocument, id=pk)
        form = DocumentVersionForm(request.POST, request.FILES)
        if form.is_valid():
            DocumentService.add_version(
                document=doc,
                file=form.cleaned_data['file'],
                changelog=form.cleaned_data['changelog'],
                user=request.user
            )
            messages.success(request, _('New document version uploaded successfully.'))
        return redirect('operations:document_detail', pk=pk)
