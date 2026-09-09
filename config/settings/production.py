"""
Production settings.

Extends base.py with production-specific hardening.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())  # noqa: F405

# ─── Security Hardening ──────────────────────────────
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# ─── Enforce critical secrets ────────────────────────
if OTP_HASH_SECRET == "INSECURE-DEV-OTP-SECRET-CHANGE-IN-PRODUCTION":  # noqa: F405
    raise ImproperlyConfigured(
        "OTP_HASH_SECRET must be set to a unique, secure value in production. "
        "Do NOT use the default development value."
    )

# ─── Use Yemen Local SMS Provider in production ──────
OTP_SETTINGS["SMS_PROVIDER"] = (  # noqa: F405
    "apps.accounts.providers.yemen_local_provider.YemenLocalOTPProvider"
)

# ─── Validate SMS provider is NOT the fake provider ──
_sms_provider = OTP_SETTINGS.get("SMS_PROVIDER", "")  # noqa: F405
if "fake" in _sms_provider.lower():
    raise ImproperlyConfigured(
        "FakeOTPProvider cannot be used in production. "
        "Configure a real SMS provider (e.g. YemenLocalOTPProvider)."
    )

# ─── CORS — restrict in production ───────────────────
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="",
    cast=Csv(),
)

# ─── Production Logging ──────────────────────────────
LOGGING["loggers"]["apps"]["level"] = "WARNING"  # type: ignore[index]
