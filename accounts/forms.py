from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from accounts.models import Role, User
from organization.models import Department, Position


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label=_('Username'),
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'current-password',
                'id': 'id_password',
            }
        ),
    )
    remember_me = forms.BooleanField(
        label=_('Remember me'),
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    preferred_language = forms.ChoiceField(
        choices=(('uz', _('Uzbek')), ('en', _('English')), ('ru', _('Russian'))),
        required=False,
        initial='en',
        label=_('Preferred Language'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.filter(is_active=True).order_by('name'),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label=_('Roles'),
    )

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
            'phone',
            'photo',
            'preferred_language',
            'department',
            'position',
            'roles',
            'is_active',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+998...'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
            'preferred_language': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'position': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        roles = cleaned_data.get('roles')
        department = cleaned_data.get('department')

        if roles:
            role_codes = {r.code for r in roles}
            if Role.Codes.RECTOR in role_codes:
                # Rector shouldn't be tied to a single department
                pass
            elif (Role.Codes.DEPARTMENT_HEAD in role_codes or Role.Codes.EMPLOYEE in role_codes) and not department:
                self.add_error('department', _('Department is required for Department Heads and Employees.'))
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserUpdateForm(forms.ModelForm):
    preferred_language = forms.ChoiceField(
        choices=(('uz', _('Uzbek')), ('en', _('English')), ('ru', _('Russian'))),
        required=False,
        initial='en',
        label=_('Preferred Language'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.filter(is_active=True).order_by('name'),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label=_('Roles'),
    )

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
            'phone',
            'photo',
            'preferred_language',
            'department',
            'position',
            'roles',
            'is_active',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
            'preferred_language': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'position': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Non-rector actors have restricted fields
        if actor and not actor.is_rector:
            self.fields['roles'].disabled = True
            self.fields['username'].disabled = True
            if actor.is_vice_rector:
                scoped_depts = actor.get_scoped_departments()
                self.fields['department'].queryset = scoped_depts
            elif actor.is_department_head:
                self.fields['department'].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        roles = cleaned_data.get('roles')
        department = cleaned_data.get('department')

        if roles:
            role_codes = {r.code for r in roles}
            if (Role.Codes.DEPARTMENT_HEAD in role_codes or Role.Codes.EMPLOYEE in role_codes) and not department:
                self.add_error('department', _('Department is required for Department Heads and Employees.'))
        return cleaned_data


class ProfileEditForm(forms.ModelForm):
    preferred_language = forms.ChoiceField(
        choices=(('uz', _('Uzbek')), ('en', _('English')), ('ru', _('Russian'))),
        required=False,
        initial='en',
        label=_('Preferred Language'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'photo', 'preferred_language']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+998...'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
        }
