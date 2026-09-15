from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_non_negative_decimal(value):
    """Validates that an amount is not negative."""
    if value is not None and value < Decimal('0.00'):
        raise ValidationError(_('Amount cannot be negative.'))


def validate_percentage(value):
    """Validates that a percentage is between 0 and 100."""
    if value is not None:
        if value < Decimal('0.00') or value > Decimal('100.00'):
            raise ValidationError(_('Percentage must be between 0.00 and 100.00.'))


def validate_positive_decimal(value):
    """Validates that an amount is strictly greater than 0."""
    if value is not None and value <= Decimal('0.00'):
        raise ValidationError(_('Amount must be strictly greater than zero.'))
