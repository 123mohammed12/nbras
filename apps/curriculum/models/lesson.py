from django.db import models
from apps.curriculum.models.subject import ContentStatus


class Lesson(models.Model):
    id = models.CharField(primary_key=True, max_length=200, help_text="مثال: 3s_sci_chem_fy_u1_l1")
    unit = models.ForeignKey(
        "curriculum.Unit",
        on_delete=models.PROTECT,
        related_name="lessons",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    estimated_minutes = models.PositiveIntegerField(default=15)
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_lessons"
        ordering = ["sort_order", "id"]
        verbose_name = "الدرس الدراسي"
        verbose_name_plural = "الدروس الدراسية"
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "sort_order"],
                name="unique_lesson_sort_order_per_unit",
            ),
        ]

    def __str__(self):
        return f"{self.unit.title} - {self.title}"
