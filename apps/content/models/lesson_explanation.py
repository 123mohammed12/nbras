import uuid
from django.db import models
from apps.curriculum.models.subject import ContentStatus


class ContentFormat(models.TextChoices):
    PLAIN_TEXT = "plain_text", "نص عادي"
    MARKDOWN = "markdown", "Markdown"


class LessonExplanation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.OneToOneField(
        "curriculum.Lesson",
        on_delete=models.CASCADE,
        related_name="explanation",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()
    content_format = models.CharField(
        max_length=20,
        choices=ContentFormat.choices,
        default=ContentFormat.MARKDOWN,
    )
    status = models.CharField(
        max_length=20,
        choices=ContentStatus.choices,
        default=ContentStatus.PUBLISHED,
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_lesson_explanations"
        verbose_name = "شرح الدرس"
        verbose_name_plural = "شروحات الدروس"

    def __str__(self):
        return f"Explanation: {self.lesson.title}"
