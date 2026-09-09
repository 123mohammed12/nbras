"""
PythonAnywhere-specific settings.

Extends production.py with PythonAnywhere platform adaptations:
- Automatic SQLite support for Free Tier (or PostgreSQL if DB_HOST is set)
- LocMemCache (zero-config, high speed for PythonAnywhere single-worker)
- SSL redirect disabled (PythonAnywhere proxy handles SSL)
- Optional FakeOTPProvider fallback for Free Tier testing without SMS API
"""

from .production import *  # noqa: F401, F403

# ─── PythonAnywhere handles SSL at the proxy level ────
# Enabling this causes infinite redirect loops on PythonAnywhere
SECURE_SSL_REDIRECT = False

# ─── Database — SQLite by default (Free plan), PostgreSQL if DB_HOST is set ──
if not config("DB_HOST", default=""):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="smart_teacher"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST"),
            "PORT": config("DB_PORT", default="5432"),
            "OPTIONS": {
                "connect_timeout": 5,
            },
        }
    }

# ─── Cache — LocMemCache (zero-config, perfect for single worker on Free plan) ──
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "smart-teacher-pa-cache",
    }
}

# ─── SMS Provider (allow FakeOTPProvider on Free plan if no SMS API is set) ──
OTP_SETTINGS["SMS_PROVIDER"] = config(
    "SMS_PROVIDER",
    default="apps.accounts.providers.fake_provider.FakeOTPProvider",
)
