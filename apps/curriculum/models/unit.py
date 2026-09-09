from django.core.exceptions import ValidationError
from django.db import models
from apps.curriculum.models.subject import ContentStatus


class Unit(models.Model):
    id = models.CharField(primary_key=True, max_length=150, help_text="مثال: 3s_sci_chem_fy_u1")
    subject = models.ForeignKey(
        "curriculum.Subject",
        on_delete=models.PROTECT,
        related_name="units",
    )
    term = models.ForeignKey(
        "curriculum.Term",
        on_delete=models.PROTECT,
        related_name="units",
        help_text="الفصل الدراسي التابع له هذه الوحدة.",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_units"
        ordering = ["sort_order", "id"]
        verbose_name = "الوحدة الدراسية"
        verbose_name_plural = "الوحدات الدراسية"
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "sort_order"],
                name="unique_unit_sort_order_per_subject",
            ),
        ]

    def clean(self):
        super().clean()
        if self.term_id and self.subject_id and hasattr(self, "term") and hasattr(self, "subject"):
            if self.term.grade_id != self.subject.grade_id or self.term.section_id != self.subject.section_id:
                raise ValidationError("الفصل الدراسي والمسار لا يطابقان المادة الدراسية المختارة.")

    def __str__(self):
        return f"{self.subject.name_ar} - {self.title}"
