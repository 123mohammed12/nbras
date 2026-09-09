import uuid

from django.conf import settings
from django.db import models


class ImportContentType(models.TextChoices):
    EXAMS = "exams", "نماذج وزارية"
    SUMMARIES = "summaries", "ملخصات"
    SMART_CARDS = "smart_cards", "بطاقات ذكية"
    MIXED = "mixed", "دفعة مختلطة"


class ImportOperation(models.TextChoices):
    VALIDATE = "validate", "تحقق ومعاينة"
    UPSERT = "upsert", "إضافة وتحديث"
    REPLACE_SCOPE = "replace_scope", "استبدال النطاق"


class ImportStatus(models.TextChoices):
    PREVIEWED = "previewed", "تمت المعاينة"
    SUCCEEDED = "succeeded", "نجح"
    FAILED = "failed", "فشل"


class ContentImportLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_type = models.CharField(max_length=20, choices=ImportContentType.choices)
    operation = models.CharField(max_length=20, choices=ImportOperation.choices)
    status = models.CharField(max_length=20, choices=ImportStatus.choices, db_index=True)
    source_names = models.JSONField(default=list, blank=True)
    source_checksum = models.CharField(max_length=64, blank=True, default="")
    report = models.JSONField(default=dict, blank=True)
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_import_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "content_import_logs"
        ordering = ["-created_at"]
        verbose_name = "سجل استيراد المحتوى"
        verbose_name_plural = "سجلات استيراد المحتوى"
        permissions = [
            ("execute_import", "Can execute validated content imports"),
        ]

    def __str__(self):
        return f"{self.get_content_type_display()} - {self.get_status_display()}"
