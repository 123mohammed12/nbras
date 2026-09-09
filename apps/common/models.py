import uuid
from django.conf import settings
from django.db import models


class IdempotencyRecord(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "قيد المعالجة"
        COMPLETED = "completed", "مكتمل"
        FAILED = "failed", "فاشل"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idempotency_records",
        null=True,
        blank=True,
    )
    actor_scope = models.CharField(max_length=255, db_index=True, default="anon")
    key = models.CharField(max_length=128, db_index=True)
    method = models.CharField(max_length=10, default="POST")
    endpoint = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PROCESSING, db_index=True
    )
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "common_idempotency_records"
        verbose_name = "سجل الإديمبوتنسي"
        verbose_name_plural = "سجلات الإديمبوتنسي"
        constraints = [
            models.UniqueConstraint(
                fields=["actor_scope", "endpoint", "key"],
                name="unique_actor_endpoint_idempotency_key",
            )
        ]
        indexes = [
            models.Index(
                fields=["expires_at", "status"],
                name="idx_idem_expires_status",
            ),
        ]

    def __str__(self):
        return f"[{self.actor_scope}] {self.key} - {self.status}"
