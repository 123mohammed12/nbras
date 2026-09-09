"""
Student Profile Model with Geographical Hierarchy Validation.

Stores personal and geographic data for registered students.
Separate from User to keep authentication data clean.
"""

import uuid

from django.conf import settings
from django.db import models
from apps.locations.validators import validate_school_location


class StudentProfile(models.Model):
    """
    Personal and geographic profile for a registered student.

    - OneToOne with User.
    - Stores full name, location references, and custom school name.
    - Location fields reference apps.locations models via ForeignKey.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    full_name = models.CharField(
        max_length=255,
        help_text="الاسم الكامل للطالب.",
    )
    governorate = models.ForeignKey(
        "locations.Governorate",
        on_delete=models.PROTECT,
        related_name="student_profiles",
        null=True,
        blank=True,
        help_text="المحافظة.",
    )
    district = models.ForeignKey(
        "locations.District",
        on_delete=models.PROTECT,
        related_name="student_profiles",
        null=True,
        blank=True,
        help_text="المديرية.",
    )
    isolation = models.ForeignKey(
        "locations.Isolation",
        on_delete=models.PROTECT,
        related_name="student_profiles",
        null=True,
        blank=True,
        help_text="العزلة.",
    )
    school = models.ForeignKey(
        "locations.School",
        on_delete=models.PROTECT,
        related_name="student_profiles",
        null=True,
        blank=True,
        help_text="المدرسة.",
    )
    custom_school_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="اسم مدرسة مخصص إذا لم تكن موجودة في القائمة.",
    )
    custom_governorate_name = models.CharField(max_length=100, blank=True, default="")
    custom_district_name = models.CharField(max_length=100, blank=True, default="")
    custom_isolation_name = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_student_profile"
        verbose_name = "ملف الطالب"
        verbose_name_plural = "ملفات الطلاب"

    def clean(self):
        super().clean()
        if self.governorate or self.district or self.isolation:
            validate_school_location(self.governorate, self.district, self.isolation)
        if self.school_id:
            if not self.governorate_id or not self.district_id:
                from django.core.exceptions import ValidationError
                raise ValidationError({"school": "اختيار مدرسة معتمدة يتطلب محافظة ومديرية معتمدتين."})
            if self.school.governorate_id != self.governorate_id or self.school.district_id != self.district_id:
                from django.core.exceptions import ValidationError
                raise ValidationError({"school": "المدرسة لا تتبع الموقع المختار."})
            if self.isolation_id and self.school.isolation_id and self.school.isolation_id != self.isolation_id:
                from django.core.exceptions import ValidationError
                raise ValidationError({"school": "المدرسة لا تتبع العزلة المختارة."})

    def __str__(self):
        return f"{self.full_name} — {self.user}"
