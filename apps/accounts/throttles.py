"""
Account-specific throttle classes.

Cache keys use hashed identifiers to avoid storing raw phone numbers.

Security (BE-12AR):
- Phone is normalized before hashing to ensure all formats produce the same key.
- If normalization fails, raw phone is hashed safely (no exception from throttle layer).
- Independent per-phone AND per-IP throttles for login/registration/reset.
- Changing IP does not bypass per-phone throttle and vice versa.
"""

import hashlib
import logging

from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger("accounts.throttles")


def _hash_identifier(*parts: str) -> str:
    """Create a safe truncated hash from multiple identifier parts."""
    raw = ":".join(p for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _normalize_phone_safe(phone: str) -> str:
    """
    Normalize phone for throttle cache key.
    Falls back to raw hash if normalization fails — never raises from throttle layer.
    """
    if not phone:
        return ""
    try:
        from apps.accounts.models import normalize_phone
        return normalize_phone(phone)
    except Exception:
        # Normalization failed — use raw value hashed safely
        return _hash_identifier("raw", phone)


class OTPRequestThrottle(SimpleRateThrottle):
    """Throttle OTP request attempts by hash(phone) + installation_id + IP."""

    scope = "otp_request"

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        installation_id = request.data.get("installation_id", "")
        ip = self.get_ident(request)
        ident = _hash_identifier(phone, installation_id, ip)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OTPVerifyThrottle(SimpleRateThrottle):
    """Throttle OTP verification attempts by hash(phone) + installation_id + IP."""

    scope = "otp_verify"

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        installation_id = request.data.get("installation_id", "")
        ip = self.get_ident(request)
        ident = _hash_identifier(phone, installation_id, ip)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class GuestCreateThrottle(SimpleRateThrottle):
    """Throttle guest account creation by installation_id + IP."""

    scope = "guest_create"

    def get_cache_key(self, request, view):
        installation_id = request.data.get("installation_id", "")
        ip = self.get_ident(request)
        ident = _hash_identifier(installation_id, ip) if installation_id else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}


# ─── Independent Phone and IP Throttles ──────────────
# These are applied as separate classes to enforce independent limits.
# Changing IP does not bypass per-phone throttle.
# Changing phone does not bypass per-IP throttle.


class LoginPhoneThrottle(SimpleRateThrottle):
    """Throttle login by normalized phone only (independent of IP)."""

    scope = "account_login"

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        if not phone:
            return None  # Cannot throttle without phone
        ident = _hash_identifier("phone", phone)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginIPThrottle(SimpleRateThrottle):
    """Throttle login by IP only (independent of phone)."""

    scope = "account_login"

    def get_cache_key(self, request, view):
        ip = self.get_ident(request)
        ident = _hash_identifier("ip", ip)
        return self.cache_format % {"scope": self.scope, "ident": ident}


# Combined LoginThrottle kept for backward compat — views can use either.
class LoginThrottle(SimpleRateThrottle):
    """Throttle login attempts by hash(phone) + IP."""

    scope = "account_login"

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        ip = self.get_ident(request)
        ident = _hash_identifier(phone, ip) if phone else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}


class RegistrationCompleteThrottle(SimpleRateThrottle):
    """Throttle registration completion by hash(phone) + IP."""

    scope = "registration_complete"

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        ip = self.get_ident(request)
        ident = _hash_identifier(phone, ip) if phone else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}


class TokenRefreshThrottle(SimpleRateThrottle):
    """Throttle token refresh requests by user ID or IP."""

    scope = "token_refresh"

    def get_cache_key(self, request, view):
        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            ident = str(request.user.id)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordResetCompleteThrottle(SimpleRateThrottle):
    """Throttle password reset attempts by hash(phone) + IP."""

    scope = "password_reset_complete"

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        ip = self.get_ident(request)
        ident = _hash_identifier(phone, ip) if phone else ip
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordChangeThrottle(SimpleRateThrottle):
    """Throttle password change requests by authenticated user ID or IP."""

    scope = "password_change"

    def get_cache_key(self, request, view):
        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            ident = str(request.user.id)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordLoginPhoneThrottle(SimpleRateThrottle):
    scope = "password_login_phone"
    rate = None

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        if not phone:
            return None
        ident = _hash_identifier("phone", phone)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordLoginIPThrottle(SimpleRateThrottle):
    scope = "password_login_ip"
    rate = None

    def get_cache_key(self, request, view):
        ip = self.get_ident(request)
        ident = _hash_identifier("ip", ip)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordRegistrationPhoneThrottle(SimpleRateThrottle):
    scope = "password_registration_phone"
    rate = None

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        if not phone:
            return None
        ident = _hash_identifier("phone", phone)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordRegistrationIPThrottle(SimpleRateThrottle):
    scope = "password_registration_ip"
    rate = None

    def get_cache_key(self, request, view):
        ip = self.get_ident(request)
        ident = _hash_identifier("ip", ip)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordResetPhoneThrottle(SimpleRateThrottle):
    scope = "password_reset_phone"
    rate = None

    def get_cache_key(self, request, view):
        phone = _normalize_phone_safe(request.data.get("phone", ""))
        if not phone:
            return None
        ident = _hash_identifier("phone", phone)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordResetIPThrottle(SimpleRateThrottle):
    scope = "password_reset_ip"
    rate = None

    def get_cache_key(self, request, view):
        ip = self.get_ident(request)
        ident = _hash_identifier("ip", ip)
        return self.cache_format % {"scope": self.scope, "ident": ident}

