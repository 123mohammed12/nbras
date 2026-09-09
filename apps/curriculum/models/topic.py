from django.db import models
from apps.curriculum.models.subject import ContentStatus


class Topic(models.Model):
    id = models.CharField(primary_key=True, max_length=250)
    lesson = models.ForeignKey(
        "curriculum.Lesson",
        on_delete=models.PROTECT,
        related_name="topics",
    )
    title = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_topics"
        ordering = ["sort_order", "id"]
        verbose_name = "موضوع تفصيلي"
        verbose_name_plural = "المواضيع التفصيلية"
        constraints = [
            models.UniqueConstraint(
                fields=["lesson", "sort_order"],
                name="unique_topic_sort_order_per_lesson",
            ),
        ]

    def __str__(self):
        return f"{self.lesson.title} - {self.title}"
