from django.contrib import admin
from communication.models import (
    ExternalIntegration,
    IntegrationSyncLog,
    NotificationPreference,
    TelegramProfile,
    UserCalendarFeed,
    WebPushSubscription,
)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'enable_in_app', 'enable_email', 'enable_telegram', 'enable_push', 'updated_at']
    search_fields = ['user__username', 'user__email']


@admin.register(TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'telegram_username', 'telegram_chat_id', 'is_verified', 'connected_at']
    search_fields = ['user__username', 'telegram_username', 'telegram_chat_id']
    list_filter = ['is_verified']


@admin.register(WebPushSubscription)
class WebPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'endpoint', 'created_at']
    search_fields = ['user__username']


@admin.register(UserCalendarFeed)
class UserCalendarFeedAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_active', 'last_accessed_at', 'created_at']
    search_fields = ['user__username']
    list_filter = ['is_active']


@admin.register(ExternalIntegration)
class ExternalIntegrationAdmin(admin.ModelAdmin):
    list_display = ['name', 'service_type', 'api_endpoint', 'is_active', 'last_sync_at']
    list_filter = ['service_type', 'is_active']
    search_fields = ['name', 'api_endpoint']


@admin.register(IntegrationSyncLog)
class IntegrationSyncLogAdmin(admin.ModelAdmin):
    list_display = ['integration', 'sync_type', 'records_processed', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['integration__name', 'error_details']
