from django.db import models


class Section(models.Model):
    id = models.CharField(primary_key=True, max_length=50, help_text="مثال: 3s_sci أو scientific")
    grade = models.ForeignKey(
        "curriculum.Grade",
        on_delete=models.CASCADE,
        related_name="sections",
    )
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150, blank=True, default="")
    code = models.CharField(max_length=50, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_sections"
        ordering = ["sort_order", "id"]
        verbose_name = "القسم / المسار"
        verbose_name_plural = "الأقسام والمسارات"

    def __str__(self):
        return f"{self.grade.name_ar} - {self.name_ar}"
