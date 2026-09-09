"""
Centralized Geographical Hierarchy Validators for locations app.

Used across models, serializers, services, Django Admin, and accounts integration.
"""

from django.core.exceptions import ValidationError


def validate_district_belongs_to_governorate(district, governorate):
    """Ensure district belongs to the specified governorate."""
    if district and governorate and district.governorate_id != governorate.id:
        raise ValidationError(
            f"المديرية '{district.name_ar}' لا تتبع المحافظة المختارة '{governorate.name_ar}'."
        )


def validate_isolation_belongs_to_district(isolation, district):
    """Ensure isolation belongs to the specified district."""
    if isolation and district and isolation.district_id != district.id:
        raise ValidationError(
            f"العزلة '{isolation.name_ar}' لا تتبع المديرية المختارة '{district.name_ar}'."
        )


def validate_school_location(governorate, district, isolation=None):
    """Ensure school location hierarchy is consistent."""
    if district and governorate and district.governorate_id != governorate.id:
        raise ValidationError(
            f"المديرية '{district.name_ar}' لا تتبع المحافظة المختارة '{governorate.name_ar}'."
        )

    if isolation and district and isolation.district_id != district.id:
        raise ValidationError(
            f"العزلة '{isolation.name_ar}' لا تتبع المديرية المختارة '{district.name_ar}'."
        )
