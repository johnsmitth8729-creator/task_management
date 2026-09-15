from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SignaturesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'signatures'
    verbose_name = _('Electronic Signatures & Verification')
