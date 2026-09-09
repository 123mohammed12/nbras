"""
User Session Model.

Tracks JWT refresh token sessions tied to a device.
Supports rotation, revocation, and logout.
"""

import uuid

from django.conf import settings
from django.db import models


class UserSession(models.Model):
    """
    Represents an active JWT session for a user on a specific device.

    - Stores the JTI (JWT ID) for the refresh token.
    - Stores a hash of the refresh token (never plaintext).
    - Supports revocation, rotation, and expiry tracking.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    device = models.ForeignKey(
        "accounts.UserDevice",
        on_delete=models.CASCADE,
        related_name="sessions",
        null=True,
        blank=True,
    )
    refresh_token_jti = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="JTI claim from the refresh token.",
    )
    refresh_token_hash = models.CharField(
        max_length=255,
        help_text="SHA-256 hash of the refresh token.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    class Meta:
        db_table = "accounts_user_session"
        ordering = ["-created_at"]
        verbose_name = "جلسة المستخدم"
        verbose_name_plural = "جلسات المستخدمين"
        indexes = [
            models.Index(fields=["user", "device", "expires_at", "revoked_at"]),
        ]
        permissions = [
            ("revoke_usersession", "Can revoke active user sessions"),
        ]

    def __str__(self):
        status = "ملغاة" if self.revoked_at else "نشطة"
        return f"Session {str(self.id)[:8]} — {self.user} [{status}]"

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    @property
    def is_active(self):
        from django.utils import timezone
        return not self.is_revoked and self.expires_at > timezone.now()
