"""
Fake OTP Provider for development and automated testing ONLY.

WARNING: This provider MUST NEVER be used in production or staging.
It will refuse to initialize in non-development environments.
"""

import logging
import uuid

from django.conf import settings

from .base import OTPProvider, SMSResult

logger = logging.getLogger("accounts.otp")

# Environments where FakeOTPProvider is allowed
_ALLOWED_ENVIRONMENTS = {"development", "testing"}


import sys


def _get_current_environment() -> str:
    """Determine the current environment from Django settings and sys.modules."""
    if "pytest" in sys.modules or "test" in sys.argv:
        return "testing"
    settings_module = str(getattr(settings, "SETTINGS_MODULE", ""))
    if "test" in settings_module or "development" in settings_module:
        return "testing" if "test" in settings_module else "development"
    if getattr(settings, "DEBUG", False):
        return "development"
    return "production"


class FakeOTPProvider(OTPProvider):
    """
    Development & test provider. Logs OTP to console and returns success.

    ⚠️  DEVELOPMENT ONLY — refuses to work in production/staging.
    """

    def __init__(self):
        super().__init__()
        env = _get_current_environment()
        if env not in _ALLOWED_ENVIRONMENTS:
            raise RuntimeError(
                f"FakeOTPProvider cannot be used in '{env}' environment. "
                f"Configure a real SMS provider for production/staging."
            )

    def send_otp(self, phone: str, code: str, purpose: str) -> SMSResult:
        msg_id = str(uuid.uuid4())[:8]

        # Use DEBUG level — will NOT appear in production logs
        logger.debug(
            "[DEV FAKE OTP] Phone: %s | Purpose: %s | MsgID: %s "
            "— ⚠️  DEVELOPMENT ONLY, code available in test fixtures",
            phone,
            purpose,
            msg_id,
        )

        # Only print to stdout in development with DEBUG=True
        if getattr(settings, "DEBUG", False):
            print(
                f"\n{'=' * 50}\n"
                f"⚠️  [FAKE OTP - DEVELOPMENT ONLY]\n"
                f"{'=' * 50}\n"
                f"  To:      {phone}\n"
                f"  Purpose: {purpose}\n"
                f"  Code:    {code}\n"
                f"  MsgID:   {msg_id}\n"
                f"{'=' * 50}\n"
            )

        return SMSResult(success=True, message_id=msg_id)
