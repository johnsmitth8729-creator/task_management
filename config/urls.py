from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import CustomSetLanguageView
from signatures.views import public_verification_view

urlpatterns = [
    path('i18n/setlang/', CustomSetLanguageView.as_view(), name='set_language'),
    path('i18n/', include('django.conf.urls.i18n')),
    path('verify/<str:verification_id>/', public_verification_view, name='public_verify_root'),
]

urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('', include('accounts.urls')),
    path('', include('organization.urls')),
    path('', include('tasks.urls')),
    path('', include('workflow.urls')),
    path('', include('files.urls')),
    path('', include('signatures.urls')),
    path('hr/', include('hr.urls', namespace='hr')),
    path('performance/', include('kpi.urls', namespace='kpi')),
    path('payroll/', include('payroll.urls', namespace='payroll')),
    path('analytics/', include('analytics.urls', namespace='analytics')),
    path('automation/', include('automation.urls', namespace='automation')),
    path('communication/', include('communication.urls', namespace='communication')),
    path('operations/', include('operations.urls', namespace='operations')),
    path('ai/', include('ai_assistant.urls', namespace='ai_assistant')),
    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler400 = 'core.views.custom_400'
handler403 = 'core.views.custom_403'
handler404 = 'core.views.custom_404'
handler500 = 'core.views.custom_500'

