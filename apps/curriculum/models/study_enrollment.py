import uuid
from django.db import models
from django.conf import settings


class StudyEnrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "نشط"
        CHANGED = "changed", "مُغيَّر"
        CANCELLED = "cancelled", "ملغى"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_enrollments",
    )
    grade = models.ForeignKey(
        "curriculum.Grade",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    section = models.ForeignKey(
        "curriculum.Section",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    academic_year = models.ForeignKey(
        "curriculum.AcademicYear",
        on_delete=models.PROTECT,
        related_name="enrollments",
        null=True,
        blank=True,
        help_text="السياق السنوي الحالي. الحقل اختياري فقط للسجلات القديمة.",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    is_active = models.BooleanField(default=True, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_study_enrollments"
        ordering = ["-created_at"]
        verbose_name = "الملف الدراسي"
        verbose_name_plural = "الملفات الدراسية"
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_active=True),
                name="unique_active_enrollment_per_user",
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.grade.name_ar} ({self.section.name_ar})"
