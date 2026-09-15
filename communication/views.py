from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
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

from communication.forms import (
    ExternalIntegrationForm,
    NotificationPreferenceForm,
)
from communication.models import (
    ExternalIntegration,
    IntegrationSyncLog,
    NotificationPreference,
    TelegramProfile,
    UserCalendarFeed,
)
from communication.services import (
    CalendarService,
    ExternalIntegrationService,
    TelegramService,
)
from core.models import AuditLog, Notification, log_audit


class NotificationCenterView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'communication/notification_center.html'
    context_object_name = 'notifications'
    paginate_by = 25

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user).order_by('-created_at')
        filter_type = self.request.GET.get('type')
        status = self.request.GET.get('status')
        if filter_type:
            qs = qs.filter(notification_type=filter_type)
        if status == 'unread':
            qs = qs.filter(is_read=False)
        elif status == 'read':
            qs = qs.filter(is_read=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['unread_count'] = Notification.objects.filter(recipient=user, is_read=False).count()
        context['total_count'] = Notification.objects.filter(recipient=user).count()
        context['current_type'] = self.request.GET.get('type', '')
        context['current_status'] = self.request.GET.get('status', 'all')
        return context


class NotificationMarkReadView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        if pk:
            notif = get_object_or_404(Notification, id=pk, recipient=request.user)
            notif.is_read = True
            notif.read_at = timezone.now()
            notif.save(update_fields=['is_read', 'read_at'])
            messages.success(request, _('Notification marked as read.'))
        else:
            Notification.objects.filter(recipient=request.user, is_read=False).update(
                is_read=True, read_at=timezone.now()
            )
            messages.success(request, _('All notifications marked as read.'))
        return redirect('communication:notification_center')


class NotificationPreferencesView(LoginRequiredMixin, View):
    template_name = 'communication/preferences.html'

    def get(self, request):
        prefs, _created = NotificationPreference.objects.get_or_create(user=request.user)
        form = NotificationPreferenceForm(instance=prefs)
        return render(request, self.template_name, {'form': form, 'prefs': prefs})

    def post(self, request):
        prefs, _created = NotificationPreference.objects.get_or_create(user=request.user)
        form = NotificationPreferenceForm(request.POST, instance=prefs)
        if form.is_valid():
            form.save()
            log_audit(
                actor=request.user,
                action=AuditLog.Actions.PREFERENCES_UPDATED,
                target_repr=f"User: {request.user.username}",
                details={'channels': {
                    'in_app': prefs.enable_in_app,
                    'email': prefs.enable_email,
                    'telegram': prefs.enable_telegram,
                    'push': prefs.enable_push
                }}
            )
            messages.success(request, _('Notification preferences updated successfully.'))
            return redirect('communication:preferences')
        return render(request, self.template_name, {'form': form, 'prefs': prefs})


class TelegramConnectView(LoginRequiredMixin, View):
    template_name = 'communication/telegram_connect.html'

    def get(self, request):
        profile = TelegramService.get_or_create_profile(request.user)
        connect_link = TelegramService.generate_connect_link(request.user)
        bot_username = TelegramService.get_bot_username()
        return render(request, self.template_name, {
            'profile': profile,
            'connect_link': connect_link,
            'bot_username': bot_username,
        })

    def post(self, request):
        # Simulation / manual confirmation of bot connection
        profile = TelegramService.get_or_create_profile(request.user)
        simulated_chat_id = request.POST.get('chat_id', '').strip() or f"tg_{request.user.username}"
        simulated_username = request.POST.get('username', '').strip() or request.user.username
        TelegramService.verify_connection(profile.verification_token, simulated_chat_id, simulated_username)
        messages.success(request, _('Telegram account successfully connected.'))
        return redirect('communication:telegram_connect')


class TelegramDisconnectView(LoginRequiredMixin, View):
    def post(self, request):
        TelegramService.disconnect(request.user)
        messages.info(request, _('Telegram account disconnected.'))
        return redirect('communication:telegram_connect')


class CalendarSettingsView(LoginRequiredMixin, View):
    template_name = 'communication/calendar_settings.html'

    def get(self, request):
        feed = CalendarService.get_or_create_feed(request.user)
        feed_url = request.build_absolute_uri(
            reverse_lazy('communication:calendar_feed', kwargs={'token': feed.secret_token})
        )
        return render(request, self.template_name, {
            'feed': feed,
            'feed_url': feed_url,
        })

    def post(self, request):
        new_token = CalendarService.regenerate_secret_token(request.user)
        messages.success(request, _('New calendar feed token generated. Please update your external calendar subscription.'))
        return redirect('communication:calendar_settings')


class CalendarFeedView(View):
    """
    Public RFC 5545 iCalendar endpoint authenticated via unique feed secret token.
    """
    def get(self, request, token):
        feed = UserCalendarFeed.objects.filter(secret_token=token, is_active=True).first()
        if not feed or not feed.user.is_active:
            raise Http404(_("Calendar feed not found or disabled."))

        ics_data = CalendarService.generate_ics_calendar(feed.user)
        response = HttpResponse(ics_data, content_type='text/calendar; charset=utf-8')
        response['Content-Disposition'] = f'inline; filename="tasks_{feed.user.username}.ics"'
        return response


class SuperadminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and (self.request.user.is_superuser or self.request.user.is_rector)


class IntegrationHubView(LoginRequiredMixin, SuperadminRequiredMixin, ListView):
    model = ExternalIntegration
    template_name = 'communication/integration_hub.html'
    context_object_name = 'integrations'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['recent_logs'] = IntegrationSyncLog.objects.select_related('integration').order_by('-created_at')[:20]
        context['total_integrations'] = ExternalIntegration.objects.count()
        context['active_integrations'] = ExternalIntegration.objects.filter(is_active=True).count()
        return context


class IntegrationCreateView(LoginRequiredMixin, SuperadminRequiredMixin, CreateView):
    model = ExternalIntegration
    form_class = ExternalIntegrationForm
    template_name = 'communication/integration_form.html'
    success_url = reverse_lazy('communication:integration_hub')

    def form_valid(self, form):
        messages.success(self.request, _('External integration configured successfully.'))
        return super().form_valid(form)


class IntegrationUpdateView(LoginRequiredMixin, SuperadminRequiredMixin, UpdateView):
    model = ExternalIntegration
    form_class = ExternalIntegrationForm
    template_name = 'communication/integration_form.html'
    success_url = reverse_lazy('communication:integration_hub')

    def form_valid(self, form):
        messages.success(self.request, _('External integration updated successfully.'))
        return super().form_valid(form)


class IntegrationSyncNowView(LoginRequiredMixin, SuperadminRequiredMixin, View):
    def post(self, request, pk):
        integration = get_object_or_404(ExternalIntegration, id=pk)
        log = ExternalIntegrationService.run_synchronization(integration, sync_type='MANUAL_TRIGGER')
        if log.status == IntegrationSyncLog.Status.SUCCESS:
            messages.success(request, _('Integration sync completed successfully (%d records processed).') % log.records_processed)
        else:
            messages.error(request, _('Integration sync failed: %s') % log.error_details)
        return redirect('communication:integration_hub')
