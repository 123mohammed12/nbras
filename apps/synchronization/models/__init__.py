import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class SyncStatus(models.TextChoices):
    RECEIVED = "received", "مستلم"
    PROCESSING = "processing", "قيد المعالجة"
    COMPLETED = "completed", "مكتمل"
    FAILED = "failed", "فاشل"
    CONFLICT = "conflict", "تعارض"
    CONFLICTED = "conflicted", "تعارض"
    UNSUPPORTED = "unsupported", "غير مدعوم"


class SyncOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sync_operations",
    )
    study_enrollment = models.ForeignKey(
        "curriculum.StudyEnrollment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    installation = models.ForeignKey(
        "accounts.UserDevice",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sync_operations",
    )
    client_operation_id = models.UUIDField(db_index=True)
    idempotency_key = models.CharField(max_length=255, db_index=True, blank=True, default="")
    operation_type = models.CharField(max_length=50, db_index=True)
    entity_type = models.CharField(max_length=50, blank=True, default="")
    entity_id = models.CharField(max_length=255, null=True, blank=True)
    normalized_payload = models.JSONField(null=True, blank=True)
    payload_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.RECEIVED,
        db_index=True,
    )
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=100, null=True, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    processing_version = models.CharField(max_length=50, default="v1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "synchronization_operations"
        ordering = ["-created_at"]
        verbose_name = "عملية مزامنة"
        verbose_name_plural = "عمليات المزامنة"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "installation", "client_operation_id"],
                name="unique_sync_operation_per_installation",
            ),
        ]

    def __str__(self):
        return f"SyncOp({self.client_operation_id}, {self.operation_type}, {self.status})"


class SyncBatchReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sync_batch_receipts",
    )
    study_enrollment = models.ForeignKey(
        "curriculum.StudyEnrollment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    installation = models.ForeignKey(
        "accounts.UserDevice",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sync_batch_receipts",
    )
    client_batch_id = models.UUIDField(db_index=True)
    payload_hash = models.CharField(max_length=64, db_index=True)
    operations_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.RECEIVED,
        db_index=True,
    )
    response_body = models.JSONField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "synchronization_batch_receipts"
        ordering = ["-received_at"]
        verbose_name = "إيصال دفعة مزامنة"
        verbose_name_plural = "إيصالات دفعات المزامنة"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "installation", "client_batch_id"],
                name="unique_sync_batch_per_installation",
            ),
        ]

    def __str__(self):
        return f"SyncBatch({self.client_batch_id}, {self.status})"


class SyncChangeAction(models.TextChoices):
    UPSERT = "upsert", "تحديث/إضافة"
    DELETE = "delete", "حذف"
    ARCHIVE = "archive", "أرشفة"
    RESTORE = "restore", "استعادة"
    ACCESS_REVOKED = "access_revoked", "إلغاء الوصول"


class SyncChange(models.Model):
    sequence = models.BigAutoField(primary_key=True)
    resource_type = models.CharField(max_length=50, db_index=True)
    resource_id = models.CharField(max_length=255, db_index=True)
    action = models.CharField(
        max_length=20,
        choices=SyncChangeAction.choices,
        default=SyncChangeAction.UPSERT,
        db_index=True,
    )
    grade = models.ForeignKey(
        "curriculum.Grade",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_changes",
    )
    section = models.ForeignKey(
        "curriculum.Section",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_changes",
    )
    subject = models.ForeignKey(
        "curriculum.Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_changes",
    )
    unit = models.ForeignKey(
        "curriculum.Unit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_changes",
    )
    lesson = models.ForeignKey(
        "curriculum.Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_changes",
    )
    resource_version = models.CharField(max_length=50, default="1")
    metadata_snapshot = models.JSONField(default=dict, blank=True)
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "synchronization_changes"
        ordering = ["sequence"]
        verbose_name = "تغيير مزامنة"
        verbose_name_plural = "تغييرات المزامنة"
        indexes = [
            models.Index(fields=["sequence", "resource_type"]),
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["changed_at"]),
        ]

    def __str__(self):
        return f"SyncChange({self.sequence}, {self.resource_type}:{self.resource_id}, {self.action})"
