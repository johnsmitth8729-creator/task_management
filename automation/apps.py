from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AutomationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'automation'
    verbose_name = _('Workflow Automation & SLA Engine')
