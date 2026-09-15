import uuid

from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Role(models.Model):
    class Codes(models.TextChoices):
        RECTOR = 'RECTOR', _('Rector')
        VICE_RECTOR = 'VICE_RECTOR', _('Vice Rector')
        DEPARTMENT_HEAD = 'DEPARTMENT_HEAD', _('Department Head')
        HR = 'HR', _('HR Manager')
        FINANCE = 'FINANCE', _('Finance / Accountant')
        EMPLOYEE = 'EMPLOYEE', _('Employee')

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
    class EmploymentStatus(models.TextChoices):
        ACTIVE = 'ACTIVE', _('Active')
        INACTIVE = 'INACTIVE', _('Inactive')
        ON_LEAVE = 'ON_LEAVE', _('On Leave')
        TERMINATED = 'TERMINATED', _('Terminated')

    class WorkPresence(models.TextChoices):
        PRESENT = 'PRESENT', _('At Work / Present')
        REMOTE = 'REMOTE', _('Working Remotely')
        ABSENT = 'ABSENT', _('Absent / Not at Work')

    class LeaveStatus(models.TextChoices):
        NONE = 'NONE', _('None / Active Duty')
        PERMISSION = 'PERMISSION', _('Excused Absence / Permission')
        VACATION = 'VACATION', _('Vacation / Annual Leave')
        SICK_LEAVE = 'SICK_LEAVE', _('Sick Leave')
        BUSINESS_TRIP = 'BUSINESS_TRIP', _('Business Trip')
        UNPAID_LEAVE = 'UNPAID_LEAVE', _('Unpaid Leave')

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
    grade = models.ForeignKey(
        'hr.EmployeeGrade',
        verbose_name=_('grade / level'),
        on_delete=models.SET_NULL,
        related_name='users',
        blank=True,
        null=True,
    )
    supervisor = models.ForeignKey(
        'self',
        verbose_name=_('supervisor'),
        on_delete=models.SET_NULL,
        related_name='subordinates',
        blank=True,
        null=True,
    )
    employment_status = models.CharField(
        _('employment status'),
        max_length=20,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE,
    )
    employment_start_date = models.DateField(_('employment start date'), default=timezone.now)
    employment_end_date = models.DateField(_('employment end date'), null=True, blank=True)
    work_presence = models.CharField(
        _('work presence'),
        max_length=20,
        choices=WorkPresence.choices,
        default=WorkPresence.PRESENT,
    )
    leave_status = models.CharField(
        _('leave / permission status'),
        max_length=20,
        choices=LeaveStatus.choices,
        default=LeaveStatus.NONE,
    )
    leave_notes = models.CharField(
        _('leave / permission details'),
        max_length=255,
        blank=True,
    )
    cv_file = models.FileField(
        _('CV / Resume (PDF)'),
        upload_to='cvs/%Y/%m/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])],
        help_text=_('Only PDF files are allowed.'),
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
            models.Index(fields=['employment_status']),
        ]
        verbose_name = _('user')
        verbose_name_plural = _('users')

    @property
    def display_name(self):
        full_name = self.get_full_name().strip()
        return full_name or self.username

    @property
    def initials(self) -> str:
        first = (self.first_name or '').strip()
        last = (self.last_name or '').strip()
        if first and last:
            return f"{first[0]}{last[0]}".upper()
        if first:
            return first[0].upper()
        if self.username:
            return self.username[:2].upper()
        return "U"

    def has_role(self, code: str) -> bool:
        return self.roles.filter(code=code, is_active=True).exists()

    @property
    def is_technical_superadmin(self) -> bool:
        return self.is_superuser

    @property
    def is_rector(self) -> bool:
        return self.has_role(Role.Codes.RECTOR)

    @property
    def is_vice_rector(self) -> bool:
        return self.has_role(Role.Codes.VICE_RECTOR)

    @property
    def is_department_head(self) -> bool:
        return self.has_role(Role.Codes.DEPARTMENT_HEAD)

    @property
    def is_hr(self) -> bool:
        return self.has_role(Role.Codes.HR)

    @property
    def is_finance(self) -> bool:
        return self.has_role(Role.Codes.FINANCE)

    @property
    def is_employee(self) -> bool:
        return self.has_role(Role.Codes.EMPLOYEE)

    @property
    def can_supervise(self) -> bool:
        """
        Determines whether this user holds organizational authority to supervise subordinates.
        Technical superadmin is isolated from the employee hierarchy.
        """
        if self.is_superuser:
            return False
        if not self.is_active or self.employment_status not in [self.EmploymentStatus.ACTIVE, self.EmploymentStatus.ON_LEAVE]:
            return False
        if self.position and self.position.can_supervise:
            return True
        if self.is_rector or self.is_vice_rector or self.is_department_head:
            return True
        return False


    @property
    def primary_role(self):
        if self.is_superuser:
            return Role(code='SUPERADMIN', name=_('Technical Superadmin'))
        active_roles = list(self.roles.filter(is_active=True).order_by('code'))
        priority = [
            Role.Codes.RECTOR,
            Role.Codes.VICE_RECTOR,
            Role.Codes.DEPARTMENT_HEAD,
            Role.Codes.HR,
            Role.Codes.FINANCE,
            Role.Codes.EMPLOYEE,
        ]
        for role_code in priority:
            for role in active_roles:
                if role.code == role_code:
                    return role
        return active_roles[0] if active_roles else None


    @property
    def is_acting_rector(self) -> bool:
        if not self.is_vice_rector:
            return False
        today = timezone.now().date()
        return self.acting_rector_delegations.filter(
            is_active=True,
            start_date__lte=today,
        ).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        ).exists()

    @property
    def can_act_as_rector(self) -> bool:
        return self.is_superuser or self.is_rector or self.is_acting_rector

    def get_scoped_departments(self):
        from organization.models import Department
        if self.is_superuser or self.can_act_as_rector:
            return Department.objects.all()
        if self.is_vice_rector:
            dept_ids = self.department_responsibilities.filter(is_active=True).values_list('department_id', flat=True)
            return Department.objects.filter(id__in=dept_ids)
        if self.department_id:
            return Department.objects.filter(id=self.department_id)
        return Department.objects.none()

    def get_scoped_users(self):
        if self.is_superuser:
            return User.objects.all()
        base_qs = User.objects.filter(is_superuser=False)
        if self.can_act_as_rector or self.is_hr:
            return base_qs
        if self.is_vice_rector:
            scoped_dept_ids = self.get_scoped_departments().values_list('id', flat=True)
            return base_qs.filter(department_id__in=scoped_dept_ids)
        if self.is_department_head and self.department_id:
            return base_qs.filter(department_id=self.department_id)
        return base_qs.filter(id=self.id)


# Create your models here.
