from django.db import models


class ContentStatus(models.TextChoices):
    DRAFT = "draft", "مسودة"
    UNDER_REVIEW = "under_review", "قيد المراجعة"
    APPROVED = "approved", "معتمد"
    PUBLISHED = "published", "منشور"
    ARCHIVED = "archived", "مؤرشف"


class Subject(models.Model):
    id = models.CharField(primary_key=True, max_length=100, help_text="مثال: 3s_sci_chem")
    grade = models.ForeignKey(
        "curriculum.Grade",
        on_delete=models.PROTECT,
        related_name="subjects",
    )
    section = models.ForeignKey(
        "curriculum.Section",
        on_delete=models.PROTECT,
        related_name="subjects",
    )
    name_ar = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    icon_path = models.FileField(upload_to="subjects/icons/", null=True, blank=True)
    cover_image_path = models.ImageField(upload_to="subjects/covers/", null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_subjects"
        ordering = ["sort_order", "id"]
        verbose_name = "المادة الدراسية"
        verbose_name_plural = "المواد الدراسية"

    def __str__(self):
        return f"{self.name_ar} ({self.grade.name_ar})"
