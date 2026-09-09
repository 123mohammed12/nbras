from django.db import models


class Grade(models.Model):
    id = models.CharField(primary_key=True, max_length=50, help_text="مثال: 3s أو grade_12")
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150, blank=True, default="")
    code = models.CharField(max_length=50, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_grades"
        ordering = ["sort_order", "id"]
        verbose_name = "الصف الدراسي"
        verbose_name_plural = "الصفوف الدراسية"

    def __str__(self):
        return self.name_ar
