import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.Model):
    class Codes(models.TextChoices):
        RECTOR = 'RECTOR', _('Rector / Superadmin')
        VICE_RECTOR = 'VICE_RECTOR', _('Vice Rector / Admin')
        DEPARTMENT_HEAD = 'DEPARTMENT_HEAD', _('Department Head')
        EMPLOYEE = 'EMPLOYEE', _('Employee / User')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(_('code'), max_length=50, choices=Codes.choices, unique=True)
    name = models.CharField(_('name'), max_length=150)
    description = models.TextField(_('description'), blank=True)
    is_active = models.BooleanField(_('active'), default=True)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = _('role')
        verbose_name_plural = _('roles')

    def __str__(self):
        return self.name


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_('email address'), unique=True)
    phone = models.CharField(_('phone'), max_length=50, blank=True)
    photo = models.ImageField(_('profile photo'), upload_to='profiles/', blank=True)
    preferred_language = models.CharField(
        _('preferred language'),
        max_length=10,
        choices=(('uz', _('Uzbek')), ('en', _('English')), ('ru', _('Russian'))),
        default='en',
    )
    department = models.ForeignKey(
        'organization.Department',
        verbose_name=_('department'),
        on_delete=models.SET_NULL,
        related_name='users',
        blank=True,
        null=True,
    )
    position = models.ForeignKey(
        'organization.Position',
        verbose_name=_('position'),
        on_delete=models.SET_NULL,
        related_name='users',
        blank=True,
        null=True,
    )
    roles = models.ManyToManyField(
        Role,
        verbose_name=_('roles'),
        related_name='users',
        blank=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        ordering = ['username']
        indexes = [
            models.Index(fields=['username']),
            models.Index(fields=['email']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = _('user')
        verbose_name_plural = _('users')

    @property
    def display_name(self):
        full_name = self.get_full_name().strip()
        return full_name or self.username

    def has_role(self, code: str) -> bool:
        return self.roles.filter(code=code, is_active=True).exists()

# Create your models here.
