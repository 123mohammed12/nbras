"""
Phone Verification (OTP) Model.

Stores HMAC-hashed OTP codes with rate-limiting counters,
purpose-based separation, and verification grant support.
"""

import uuid

from django.db import models


class PhoneVerification(models.Model):
    """
    Tracks OTP verification requests.

    - OTP codes are stored as HMAC-SHA256 hashes (never plaintext).
    - Each record tracks attempts, resends, and expiry.
    - Verification grant enables secure one-time proof of verification.
    - Rate limiting is enforced per phone + purpose + installation_id.
    """

    class Purpose(models.TextChoices):
        REGISTER = "register", "تسجيل حساب"
        LOGIN = "login", "تسجيل دخول"
        CHANGE_PHONE = "change_phone", "تغيير رقم الهاتف"
        RECOVER_ACCOUNT = "recover_account", "استعادة الحساب"
        RESET_PASSWORD = "reset_password", "إعادة تعيين كلمة المرور"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=15, db_index=True)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, db_index=True)
    code_hash = models.CharField(
        max_length=255,
        help_text="HMAC-SHA256 hash of OTP code. Never store plaintext.",
    )
    request_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        help_text="Unique identifier for this OTP request, returned to client.",
    )
    verification_grant_hash = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="HMAC-SHA256 hash of verification grant token. Set after successful OTP verify.",
    )
    attempts_count = models.PositiveIntegerField(default=0)
    resend_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(auto_now_add=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    installation_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    class Meta:
        db_table = "accounts_phone_verification"
        ordering = ["-created_at"]
        verbose_name = "التحقق من الهاتف"
        verbose_name_plural = "طلبات التحقق من الهاتف"
        indexes = [
            models.Index(fields=["phone", "purpose", "expires_at"]),
        ]

    def __str__(self):
        return f"OTP {self.phone} ({self.get_purpose_display()}) — {self.request_id}"

    @property
    def is_verified(self):
        return self.verified_at is not None

    @property
    def is_consumed(self):
        return self.consumed_at is not None
