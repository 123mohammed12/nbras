"""
Staging settings.

Extends base.py with staging-specific configuration.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())  # noqa: F405

# ─── Use Yemen Local SMS Provider in staging ─────────
OTP_SETTINGS["SMS_PROVIDER"] = (  # noqa: F405
    "apps.accounts.providers.yemen_local_provider.YemenLocalOTPProvider"
)

# ─── Validate SMS provider is NOT the fake provider ──
_sms_provider = OTP_SETTINGS.get("SMS_PROVIDER", "")  # noqa: F405
if "fake" in _sms_provider.lower():
    raise ImproperlyConfigured(
        "FakeOTPProvider cannot be used in staging. "
        "Configure a real SMS provider."
    )
