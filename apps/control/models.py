"""
Control Models.
Defines the Central Append-Only Operational Audit Log (ADM-09).
"""

import uuid
from django.conf import settings
from django.db import models


class ControlAuditLog(models.Model):
    """
    Central Append-Only Operational Audit Log for high-impact actions in /control/.
    Staff cannot edit or delete records.
    Never stores passwords, tokens, hashes, or sensitive credentials in metadata.
    """

    class ActionChoices(models.TextChoices):
        # Sessions
        SESSION_REVOKE = "session_revoke", "سحب جلسة"
        SESSION_REVOKE_ALL = "session_revoke_all", "سحب جميع الجلسات"
        # Subscriptions
        SUBSCRIPTION_ACTIVATE = "subscription_activate", "تفعيل اشتراك مباشر"
        SUBSCRIPTION_REVOKE = "subscription_revoke", "إلغاء/سحب اشتراك"
        CODE_BATCH_GENERATE = "code_batch_generate", "توليد دفعة رموز تفعيل"
        CODE_BATCH_REVOKE = "code_batch_revoke", "إلغاء دفعة رموز تفعيل"
        # Notifications
        NOTIFICATION_SCHEDULE = "notification_schedule", "جدولة إشعار"
        NOTIFICATION_PUBLISH = "notification_publish", "نشر إشعار فوري"
        NOTIFICATION_CANCEL = "notification_cancel", "إلغاء إشعار"
        # Content / Question Bank
        QUESTION_PUBLISH = "question_publish", "نشر سؤال"
        QUESTION_RETIRE = "question_retire", "أرشفة/استبعاد سؤال"
        QUESTION_REVIEW = "question_review", "مراجعة/اعتماد سؤال"
        # Assessments
        MINISTERIAL_SYNC = "ministerial_sync", "مزامنة امتحان وزاري"
        TRAINING_SYNC = "training_sync", "مزامنة دفعات تدريبية"
        BLUEPRINT_PUBLISH = "blueprint_publish", "نشر مخطط اختبار"
        # Imports
        IMPORT_EXECUTE = "import_execute", "تنفيذ عملية استيراد"
        # Generic
        OTHER = "other", "عملية تشغيلية أخرى"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="control_audit_logs",
        help_text="الموظف أو المدير الذي نفذ العملية.",
    )
    action = models.CharField(
        max_length=50,
        choices=ActionChoices.choices,
        db_index=True,
        help_text="رمز العملية المنفذة.",
    )
    target_type = models.CharField(
        max_length=60,
        db_index=True,
        help_text="نوع الكائن المستهدف (مثل: user_session, subscription, notification...).",
    )
    target_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="المعرّف الفريد للهدف المستهدف.",
    )
    target_repr = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="وصف أو عنوان الهدف لسهولة القراءة والبحث.",
    )
    reason = models.TextField(
        blank=True,
        default="",
        help_text="سبب تنفيذ العملية إن وجد.",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="بيانات سياقية آمنة وخالية من الأسرار والرموز الحساسة.",
    )
    request_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        help_text="معرّف الطلب أو التتبع (Correlation ID) إن توفر.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="عنوان IP داخلي للأمان والتدقيق الداخلي فقط.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "control_audit_log"
        ordering = ["-created_at"]
        verbose_name = "سجل تدقيق العمليات"
        verbose_name_plural = "سجلات تدقيق العمليات"
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def __str__(self):
        actor_name = self.actor.phone if self.actor else "System"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_name}: {self.get_action_display()} -> {self.target_repr or self.target_type}"
