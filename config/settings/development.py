"""
Development settings.

Extends base.py with development-specific configuration.
"""

from .base import *  # noqa: F401, F403

DEBUG = True

# ─── Development-only apps ────────────────────────────
# INSTALLED_APPS += []

# ─── Email Backend (console) ──────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ─── CORS — allow all in development ─────────────────
CORS_ALLOW_ALL_ORIGINS = True

# ─── Use Fake OTP Provider in development ────────────
OTP_SETTINGS["SMS_PROVIDER"] = (
    "apps.accounts.providers.fake_provider.FakeOTPProvider"
)

# ─── Cache — LocMemCache for reliable local development ────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "smart-teacher-dev-cache",
    }
}

# ─── Logging — verbose in development ────────────────
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # type: ignore[index]
