import os
import uuid
from django.core.exceptions import ValidationError
from django.db import models
from apps.curriculum.models.subject import ContentStatus
from apps.content.models.lesson_explanation import LessonExplanation, ContentFormat


def generate_summary_file_path(instance, filename: str) -> str:
    ext = filename.split(".")[-1].lower() if "." in filename else "pdf"
    return f"content/summaries/{uuid.uuid4().hex}.{ext}"


def generate_flashcard_front_image_path(instance, filename: str) -> str:
    ext = filename.split(".")[-1].lower() if "." in filename else "png"
    return f"content/flashcards/front/{uuid.uuid4().hex}.{ext}"


def generate_flashcard_back_image_path(instance, filename: str) -> str:
    ext = filename.split(".")[-1].lower() if "." in filename else "png"
    return f"content/flashcards/back/{uuid.uuid4().hex}.{ext}"


def generate_content_link_file_path(instance, filename: str) -> str:
    ext = filename.split(".")[-1].lower() if "." in filename else "bin"
    return f"content/links/files/{uuid.uuid4().hex}.{ext}"


def generate_content_link_thumbnail_path(instance, filename: str) -> str:
    ext = filename.split(".")[-1].lower() if "." in filename else "jpg"
    return f"content/links/thumbnails/{uuid.uuid4().hex}.{ext}"


class SummaryType(models.TextChoices):
    SUBJECT = "subject", "ملخص مادة"
    UNIT = "unit", "ملخص وحدة"
    LESSON = "lesson", "ملخص درس"
    FINAL_REVIEW = "final_review", "مراجعة نهائية"
    QUICK_REVIEW = "quick_review", "مراجعة سريعة"


class Summary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    summary_type = models.CharField(max_length=20, choices=SummaryType.choices, default=SummaryType.LESSON, db_index=True)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True, related_name="summaries")
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="summaries")
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True, related_name="summaries")
    body = models.TextField(null=True, blank=True)
    file_path = models.FileField(upload_to=generate_summary_file_path, null=True, blank=True)
    file_name = models.CharField(max_length=255, null=True, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    file_checksum = models.CharField(max_length=64, null=True, blank=True)
    mime_type = models.CharField(max_length=100, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True)
    is_downloadable = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_summaries"
        ordering = ["sort_order", "-created_at"]
        verbose_name = "الملخص"
        verbose_name_plural = "الملخصات"

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if not self.body and not self.file_path:
            raise ValidationError("يجب أن يحتوي الملخص على نص أو ملف مرفق على الأقل.")

        if self.summary_type == SummaryType.LESSON and not self.lesson:
            raise ValidationError("ملخص الدرس يجب أن يحدد الدرس التابع له.")
        elif self.summary_type == SummaryType.UNIT and not self.unit and not self.lesson:
            raise ValidationError("ملخص الوحدة يجب أن يحدد الوحدة التابع لها.")

        if self.lesson:
            if self.unit and self.lesson.unit != self.unit:
                raise ValidationError("الوحدة المحددة لا تطابق وحدة الدرس التابع له الملخص.")
            if self.subject and self.lesson.unit and self.lesson.unit.subject != self.subject:
                raise ValidationError("المادة المحددة لا تطابق مادة الدرس التابع له الملخص.")

    def save(self, *args, **kwargs):
        # Auto fill parent unit & subject from lesson
        if self.lesson and self.lesson.unit:
            self.unit = self.lesson.unit
            self.subject = self.lesson.unit.subject
        elif self.unit and self.unit.subject:
            self.subject = self.unit.subject

        self.full_clean()
        super().save(*args, **kwargs)


class FlashcardDeck(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True, related_name="flashcard_decks")
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="flashcard_decks")
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True, related_name="flashcard_decks")
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_flashcard_decks"
        ordering = ["sort_order", "-created_at"]
        verbose_name = "حزمة البطاقات"
        verbose_name_plural = "حزم البطاقات التعليمية"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.lesson and self.lesson.unit:
            self.unit = self.lesson.unit
            self.subject = self.lesson.unit.subject
        elif self.unit and self.unit.subject:
            self.subject = self.unit.subject
        super().save(*args, **kwargs)


class Flashcard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deck = models.ForeignKey(FlashcardDeck, on_delete=models.CASCADE, related_name="cards")
    front_text = models.TextField(null=True, blank=True)
    back_text = models.TextField(null=True, blank=True)
    front_image_path = models.ImageField(upload_to=generate_flashcard_front_image_path, null=True, blank=True)
    back_image_path = models.ImageField(upload_to=generate_flashcard_back_image_path, null=True, blank=True)
    explanation = models.TextField(null=True, blank=True)
    difficulty = models.CharField(max_length=20, default="medium")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_flashcards"
        ordering = ["sort_order", "id"]
        verbose_name = "بطاقة تعليمية"
        verbose_name_plural = "البطاقات التعليمية"
        constraints = [
            models.UniqueConstraint(
                fields=["deck", "sort_order"],
                name="unique_flashcard_sort_order_per_deck",
            )
        ]

    def __str__(self):
        return f"Card {self.sort_order} - {self.deck.title}"

    def clean(self):
        super().clean()
        if not self.front_text and not self.front_image_path:
            raise ValidationError("يجب أن يحتوي وجه البطاقة الأمامي على نص أو صورة على الأقل.")
        if not self.back_text and not self.back_image_path:
            raise ValidationError("يجب أن يحتوي ظهر البطاقة الخلفي على نص أو صورة على الأقل.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class LinkType(models.TextChoices):
    VIDEO = "video", "فيديو"
    YOUTUBE = "youtube", "يوتيوب"
    ARTICLE = "article", "مقالة"
    WEBSITE = "website", "موقع"
    PDF = "pdf", "ملف PDF"
    FILE = "file", "ملف"
    OTHER = "other", "آخر"


class ContentLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    url = models.URLField(max_length=500)
    link_type = models.CharField(max_length=20, choices=LinkType.choices, default=LinkType.VIDEO, db_index=True)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True, related_name="content_links")
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="content_links")
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True, related_name="content_links")
    description = models.TextField(blank=True, default="")
    thumbnail_path = models.ImageField(upload_to=generate_content_link_thumbnail_path, null=True, blank=True)
    attached_file_path = models.FileField(upload_to=generate_content_link_file_path, null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True)
    is_external = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_links"
        ordering = ["sort_order", "-created_at"]
        verbose_name = "رابط المحتوى"
        verbose_name_plural = "روابط المحتوى"

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.url:
            lower_url = self.url.lower().strip()
            if not lower_url.startswith("http://") and not lower_url.startswith("https://"):
                raise ValidationError("الرابط الخارجي يجب أن يبدأ بـ http:// أو https:// فقط.")
            forbidden_schemes = ["javascript:", "data:", "file:", "ftp:"]
            if any(lower_url.startswith(scheme) for scheme in forbidden_schemes):
                raise ValidationError("مخطط الرابط غير مسموح به لأسباب أمنية.")

    def save(self, *args, **kwargs):
        if self.lesson and self.lesson.unit:
            self.unit = self.lesson.unit
            self.subject = self.lesson.unit.subject
        elif self.unit and self.unit.subject:
            self.subject = self.unit.subject

        self.full_clean()
        super().save(*args, **kwargs)


__all__ = [
    "LessonExplanation",
    "ContentFormat",
    "SummaryType",
    "Summary",
    "FlashcardDeck",
    "Flashcard",
    "LinkType",
    "ContentLink",
]
