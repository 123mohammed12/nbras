from django.core.exceptions import ValidationError
from django.db import models


def build_scoped_term_id(*, section_id: str, term_id: str) -> str:
    """Return a globally unique term id while accepting legacy short ids."""
    raw_id = str(term_id or "").strip()
    scope = str(section_id or "").strip()
    if not raw_id or not scope:
        return raw_id
    prefix = f"{scope}_"
    return raw_id if raw_id.startswith(prefix) else f"{prefix}{raw_id}"


class Term(models.Model):
    id = models.CharField(primary_key=True, max_length=120, help_text="مثال: 3s_sci_fy أو 9th_sci_t1")
    grade = models.ForeignKey(
        "curriculum.Grade",
        on_delete=models.PROTECT,
        related_name="terms",
    )
    section = models.ForeignKey(
        "curriculum.Section",
        on_delete=models.PROTECT,
        related_name="terms",
    )
    name_ar = models.CharField(max_length=150)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_terms"
        ordering = ["sort_order", "id"]
        verbose_name = "الفصل الدراسي"
        verbose_name_plural = "الفصول الدراسية"

    def __str__(self):
        return f"{self.name_ar} - {self.grade.name_ar}"

    def clean(self):
        super().clean()
        if self.grade_id and self.section_id and self.section.grade_id != self.grade_id:
            raise ValidationError("المسار لا ينتمي إلى الصف المحدد للترم.")
