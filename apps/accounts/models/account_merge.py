"""
Account Merge Model.

Audit trail and lock mechanism for merging a guest account into a target registered user.
"""

import uuid

from django.conf import settings
from django.db import models


class AccountMerge(models.Model):
    """
    Tracks account merge operations.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "قيد الانتظار"
        PROCESSING = "processing", "قيد المعالجة"
        COMPLETED = "completed", "مكتمل"
        FAILED = "failed", "فاشل"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_guest = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="merges_as_source",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="merges_as_target",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    conflict_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_account_merge"
        ordering = ["-created_at"]
        verbose_name = "دمج الحساب"
        verbose_name_plural = "عمليات دمج الحسابات"

    def __str__(self):
        return f"Merge {self.source_guest_id} -> {self.target_user_id} [{self.status}]"
