from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from accounts.forms import LoginForm, ProfileEditForm, UserCreateForm, UserUpdateForm
from accounts.models import Role, User
from accounts.permissions import (
    RectorRequiredMixin,
    ScopedUserAccessMixin,
    can_edit_user,
    can_view_user,
)
from core.models import AuditLog, log_audit
from organization.models import Department, Position


class UserLoginView(LoginView):
    authentication_form = LoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        remember_me = form.cleaned_data.get('remember_me')
        if not remember_me:
            self.request.session.set_expiry(0)
        else:
            self.request.session.set_expiry(None)
        return super().form_valid(form)


class UserLogoutView(LogoutView):
    http_method_names = ['post', 'options']


class UserListView(LoginRequiredMixin, ListView):
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'user_list'
    paginate_by = 12

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        # Employees cannot view the user management directory
        if request.user.is_employee and not (request.user.is_rector or request.user.is_vice_rector or request.user.is_department_head):
            raise PermissionDenied(_('You do not have permission to view the employee directory.'))
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        qs = user.get_scoped_users().select_related('department', 'position').prefetch_related('roles')

        query = self.request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
                | Q(phone__icontains=query)
            )

        dept_id = self.request.GET.get('department', '').strip()
        if dept_id:
            qs = qs.filter(department_id=dept_id)

        pos_id = self.request.GET.get('position', '').strip()
        if pos_id:
            qs = qs.filter(position_id=pos_id)

        role_code = self.request.GET.get('role', '').strip()
        if role_code:
            qs = qs.filter(roles__code=role_code)

        status = self.request.GET.get('status', '').strip()
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        return qs.order_by('first_name', 'last_name', 'username')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['search_query'] = self.request.GET.get('q', '')
        context['selected_department'] = self.request.GET.get('department', '')
        context['selected_position'] = self.request.GET.get('position', '')
        context['selected_role'] = self.request.GET.get('role', '')
        context['selected_status'] = self.request.GET.get('status', '')

        # Filter options according to scope
        context['departments'] = user.get_scoped_departments().filter(is_active=True).order_by('name')
        context['positions'] = Position.objects.filter(is_active=True).order_by('name')
        context['roles'] = Role.objects.filter(is_active=True).order_by('name')
        context['total_users'] = self.get_queryset().count()
        return context


class UserDetailView(ScopedUserAccessMixin, DetailView):
    model = User
    template_name = 'accounts/user_detail.html'
    context_object_name = 'profile_user'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_edit'] = can_edit_user(self.request.user, self.object)
        return context


class UserCreateView(RectorRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('user_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        log_audit(
            actor=self.request.user,
            action=AuditLog.Actions.USER_CREATED,
            target_repr=self.object.display_name,
            details={
                'user_id': str(self.object.id),
                'username': self.object.username,
                'email': self.object.email,
                'department': self.object.department.name if self.object.department else None,
            },
            request=self.request,
        )
        messages.success(self.request, _('User "%(name)s" created successfully.') % {'name': self.object.display_name})
        return response


class UserUpdateView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/user_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        target_user = self.get_object()
        if not can_edit_user(request.user, target_user):
            raise PermissionDenied(_('You do not have permission to edit this user.'))
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['actor'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('user_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        log_audit(
            actor=self.request.user,
            action=AuditLog.Actions.USER_UPDATED,
            target_repr=self.object.display_name,
            details={
                'user_id': str(self.object.id),
                'username': self.object.username,
                'is_active': self.object.is_active,
            },
            request=self.request,
        )
        messages.success(self.request, _('User "%(name)s" updated successfully.') % {'name': self.object.display_name})
        return response


class UserToggleActiveView(RectorRequiredMixin, View):
    def post(self, request, pk):
        target_user = get_object_or_404(User, pk=pk)
        if target_user.id == request.user.id:
            messages.error(request, _('You cannot deactivate your own account.'))
            return redirect('user_detail', pk=target_user.pk)

        target_user.is_active = not target_user.is_active
        target_user.save(update_fields=['is_active', 'updated_at'])

        action = AuditLog.Actions.USER_ACTIVATED if target_user.is_active else AuditLog.Actions.USER_DEACTIVATED
        log_audit(
            actor=request.user,
            action=action,
            target_repr=target_user.display_name,
            details={'is_active': target_user.is_active},
            request=request,
        )
        action_label = _('activated') if target_user.is_active else _('deactivated')
        messages.success(request, _('User %(name)s was %(action)s.') % {'name': target_user.display_name, 'action': action_label})
        return redirect('user_detail', pk=target_user.pk)


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['profile_user'] = self.request.user
        return context


class ProfileEditView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = ProfileEditForm
    template_name = 'accounts/profile_edit.html'
    success_url = reverse_lazy('profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        response = super().form_valid(form)
        log_audit(
            actor=self.request.user,
            action=AuditLog.Actions.USER_UPDATED,
            target_repr=self.request.user.display_name,
            details={'self_update': True},
            request=self.request,
        )
        messages.success(self.request, _('Your profile has been updated.'))
        return response
