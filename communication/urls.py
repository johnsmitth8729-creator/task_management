from django.urls import path
from communication import views

app_name = 'communication'

urlpatterns = [
    # Notification Center & User Preferences
    path('notifications/', views.NotificationCenterView.as_view(), name='notification_center'),
    path('notifications/read/', views.NotificationMarkReadView.as_view(), name='notification_mark_all_read'),
    path('notifications/<uuid:pk>/read/', views.NotificationMarkReadView.as_view(), name='notification_mark_read'),
    path('preferences/', views.NotificationPreferencesView.as_view(), name='preferences'),

    # Telegram Bot Integration
    path('telegram/', views.TelegramConnectView.as_view(), name='telegram_connect'),
    path('telegram/disconnect/', views.TelegramDisconnectView.as_view(), name='telegram_disconnect'),

    # iCalendar Feeds
    path('calendar/', views.CalendarSettingsView.as_view(), name='calendar_settings'),
    path('calendar/feed/<str:token>/', views.CalendarFeedView.as_view(), name='calendar_feed'),

    # Superadmin Integration Hub
    path('integrations/', views.IntegrationHubView.as_view(), name='integration_hub'),
    path('integrations/new/', views.IntegrationCreateView.as_view(), name='integration_create'),
    path('integrations/<uuid:pk>/edit/', views.IntegrationUpdateView.as_view(), name='integration_update'),
    path('integrations/<uuid:pk>/sync/', views.IntegrationSyncNowView.as_view(), name='integration_sync'),
]
