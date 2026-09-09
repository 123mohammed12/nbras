"""
Custom User Model for Smart Teacher Platform.

Single table for both guests and registered users.
Phone-based authentication (no username as primary login).
"""

import re
import uuid
import random
import string
import unicodedata

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models

from apps.accounts.managers import UserManager


def generate_public_code():
    """Generate a unique 8-digit public code prefixed with STU-."""
    digits = "".join(random.choices(string.digits, k=8))
    return f"STU-{digits}"


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model.

    - Both guests and registered users live in the same table.
    - Phone is the unique identifier for registered users.
    - public_code is a short human-readable code for support.
    - Does NOT use the traditional 'username' as login method.
    """

    class AccountType(models.TextChoices):
        GUEST = "guest", "زائر"
        REGISTERED = "registered", "مسجل"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    public_code = models.CharField(
        max_length=20,
        unique=True,
        default=generate_public_code,
        help_text="رمز عام قصير للعرض والدعم الفني.",
    )
    account_type = models.CharField(
        max_length=12,
        choices=AccountType.choices,
        default=AccountType.GUEST,
        db_index=True,
    )

    # ─── Phone ────────────────────────────────────
    phone = models.CharField(
        max_length=15,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        validators=[
            RegexValidator(
                regex=r"^\+9677\d{8}$",
                message="رقم الهاتف يجب أن يكون بصيغة +9677XXXXXXXX",
            ),
        ],
        help_text="رقم الهاتف بصيغة يمنية (+9677XXXXXXXX). فارغ للزائر.",
    )
    phone_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="وقت التحقق من رقم الهاتف.",
    )
    upgraded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="وقت تحويل الزائر إلى مستخدم مسجل.",
    )

    # ─── Django Standard Fields ───────────────────
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []  # No required fields for createsuperuser beyond password

    class Meta:
        db_table = "accounts_user"
        ordering = ["-created_at"]
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"
        constraints = [
            # Phone must be unique when not null (handled by unique=True on field,
            # but adding explicit constraint for documentation)
            models.UniqueConstraint(
                fields=["phone"],
                condition=models.Q(phone__isnull=False),
                name="unique_phone_when_not_null",
            ),
        ]

    def __str__(self):
        if self.account_type == self.AccountType.GUEST:
            return f"زائر ({self.public_code})"
        return f"{self.phone} ({self.public_code})"

    @property
    def is_guest(self):
        return self.account_type == self.AccountType.GUEST

    @property
    def is_registered(self):
        return self.account_type == self.AccountType.REGISTERED

    def clean(self):
        """Normalize phone number before saving."""
        super().clean()
        if self.phone:
            self.phone = normalize_phone(self.phone)


def normalize_phone(phone: str) -> str:
    """
    Normalize a Yemeni phone number to the +9677XXXXXXXX format.

    Supports inputs like:
      - 7XXXXXXXX       → +9677XXXXXXXX
      - 07XXXXXXXX      → +9677XXXXXXXX
      - 9677XXXXXXXX    → +9677XXXXXXXX
      - +9677XXXXXXXX   → +9677XXXXXXXX
      - 009677XXXXXXXX  → +9677XXXXXXXX

    Raises InvalidPhoneError for:
      - Letters or non-digit characters
      - Unicode digits (fullwidth, Arabic-Indic, etc.)
      - Invisible characters
      - Wrong number of digits
      - Non-Yemeni country codes
    """
    from apps.accounts.exceptions import InvalidPhoneError

    if not isinstance(phone, str) or not phone:
        raise InvalidPhoneError("رقم الهاتف يجب أن يكون نصاً غير فارغ.")

    # Normalize Unicode to NFKC (fullwidth digits → ASCII digits)
    phone = unicodedata.normalize("NFKC", phone)

    # Remove allowed formatting characters
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    # Remove invisible Unicode characters
    phone = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060]", "", phone)

    # Validate: only digits allowed (with optional leading +)
    cleaned = phone.lstrip("+")
    if not cleaned:
        raise InvalidPhoneError("رقم الهاتف فارغ بعد التنظيف.")

    if not cleaned.isdigit():
        raise InvalidPhoneError("رقم الهاتف يحتوي على محارف غير مسموحة.")

    # Verify all characters in cleaned are ASCII digits (not Arabic-Indic, etc.)
    if not re.match(r"^[0-9]+$", cleaned):
        raise InvalidPhoneError("رقم الهاتف يحتوي على أرقام غير لاتينية.")

    # Normalize to +9677XXXXXXXX
    if phone.startswith("+"):
        result = phone
    elif phone.startswith("00"):
        result = "+" + phone[2:]
    elif phone.startswith("967"):
        result = "+" + phone
    elif phone.startswith("0"):
        result = "+967" + phone[1:]
    elif phone.startswith("7"):
        result = "+967" + phone
    else:
        raise InvalidPhoneError("رقم الهاتف يجب أن يبدأ بـ 7 أو 07 أو 967 أو +967 أو 00967.")

    # Final strict validation
    if not re.match(r"^\+9677\d{8}$", result):
        raise InvalidPhoneError(
            "رقم الهاتف يجب أن يكون بصيغة +9677XXXXXXXX (12 رقماً بعد +)."
        )

    return result
