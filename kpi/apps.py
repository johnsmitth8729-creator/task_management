from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class KpiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'kpi'
    verbose_name = _('Performance & KPI')
