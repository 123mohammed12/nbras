"""
Locations Models: Governorate, District, Isolation, School.
"""

from django.core.exceptions import ValidationError
from django.db import models
from apps.locations.validators import (
    validate_district_belongs_to_governorate,
    validate_isolation_belongs_to_district,
    validate_school_location,
)


class Governorate(models.Model):
    """المحافظة"""
    name_ar = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_governorate"
        ordering = ["sort_order", "name_ar"]
        verbose_name = "محافظة"
        verbose_name_plural = "المحافظات"

    def __str__(self):
        return self.name_ar


class District(models.Model):
    """المديرية"""
    governorate = models.ForeignKey(
        Governorate,
        on_delete=models.PROTECT,
        related_name="districts",
    )
    name_ar = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_district"
        ordering = ["sort_order", "name_ar"]
        verbose_name = "مديرية"
        verbose_name_plural = "المديريات"
        constraints = [
            models.UniqueConstraint(
                fields=["governorate", "code"],
                name="unique_governorate_district_code",
            ),
        ]

    def __str__(self):
        return f"{self.name_ar} ({self.governorate.name_ar})"


class Isolation(models.Model):
    """العزلة"""
    district = models.ForeignKey(
        District,
        on_delete=models.PROTECT,
        related_name="isolations",
    )
    name_ar = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_isolation"
        ordering = ["sort_order", "name_ar"]
        verbose_name = "عزلة"
        verbose_name_plural = "العزل"
        constraints = [
            models.UniqueConstraint(
                fields=["district", "code"],
                name="unique_district_isolation_code",
            ),
        ]

    def clean(self):
        super().clean()
        if self.district_id and hasattr(self, "district"):
            validate_district_belongs_to_governorate(self.district, self.district.governorate)

    def __str__(self):
        return f"{self.name_ar} ({self.district.name_ar})"


class School(models.Model):
    """المدرسة"""

    class SchoolType(models.TextChoices):
        PUBLIC = "public", "حكومي"
        PRIVATE = "private", "خاص"

    class GenderType(models.TextChoices):
        BOYS = "boys", "بنين"
        GIRLS = "girls", "بنات"
        MIXED = "mixed", "مختلط"

    governorate = models.ForeignKey(
        Governorate,
        on_delete=models.PROTECT,
        related_name="schools",
    )
    district = models.ForeignKey(
        District,
        on_delete=models.PROTECT,
        related_name="schools",
    )
    isolation = models.ForeignKey(
        Isolation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schools",
    )
    name_ar = models.CharField(max_length=200)
    code = models.CharField(max_length=50, null=True, blank=True)
    school_type = models.CharField(
        max_length=10,
        choices=SchoolType.choices,
        default=SchoolType.PUBLIC,
    )
    gender_type = models.CharField(
        max_length=10,
        choices=GenderType.choices,
        default=GenderType.MIXED,
    )
    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_school"
        ordering = ["name_ar"]
        verbose_name = "مدرسة"
        verbose_name_plural = "المدارس"
        indexes = [
            models.Index(fields=["governorate", "district", "isolation"]),
            models.Index(fields=["name_ar"]),
        ]

    def clean(self):
        super().clean()
        validate_school_location(self.governorate, self.district, self.isolation)

    def __str__(self):
        return f"{self.name_ar} ({self.district.name_ar})"
