from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AcademicYear(models.Model):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "قادم"
        ACTIVE = "active", "نشط"
        CLOSED = "closed", "منتهي"

    code = models.CharField(primary_key=True, max_length=20)
    name_ar = models.CharField(max_length=100)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPCOMING, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_academic_years"
        ordering = ["-starts_at"]
        verbose_name = "العام الدراسي"
        verbose_name_plural = "الأعوام الدراسية"
        constraints = [
            models.UniqueConstraint(
                fields=["status"],
                condition=models.Q(status="active"),
                name="unique_active_academic_year",
            )
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("نهاية العام الدراسي يجب أن تكون بعد بدايته.")

    @property
    def is_current(self):
        now = timezone.now()
        return self.status == self.Status.ACTIVE and self.starts_at <= now < self.ends_at

    def __str__(self):
        return self.name_ar or self.code
