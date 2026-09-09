"""
Yemen Local SMS OTP Provider.

Integrates with local Yemeni SMS gateway HTTP APIs.
Fails explicitly if not configured — never falls back to printing OTP codes.
"""

import logging
import uuid

import requests
from django.conf import settings

from .base import OTPProvider, SMSResult

logger = logging.getLogger("accounts.otp")


class YemenLocalOTPProvider(OTPProvider):
    """
    Real SMS Provider connecting to local Yemeni SMS Gateway API.

    Requires YEMEN_SMS_API_URL and YEMEN_SMS_API_KEY to be configured.
    Fails explicitly if configuration is missing — no fallback to console.
    """

    def __init__(self):
        super().__init__()
        self.api_url = getattr(settings, "YEMEN_SMS_API_URL", None)
        self.api_key = getattr(settings, "YEMEN_SMS_API_KEY", None)
        self.sender_id = getattr(settings, "YEMEN_SMS_SENDER_ID", "SmartTeacher")

        if not self.api_url:
            raise RuntimeError(
                "YEMEN_SMS_API_URL is not configured. "
                "Set it in your environment or use FakeOTPProvider for development."
            )

    def send_otp(self, phone: str, code: str, purpose: str) -> SMSResult:
        # Never log the OTP code in production
        message = f"رمز التحقق لمنصة المعلم الذكي هو: {code}"

        try:
            payload = {
                "api_key": self.api_key,
                "sender": self.sender_id,
                "mobile": phone.replace("+", ""),
                "message": message,
            }
            response = requests.post(self.api_url, json=payload, timeout=10)
            if response.status_code == 200:
                resp_json = response.json()
                msg_id = resp_json.get("message_id", str(uuid.uuid4())[:8])
                logger.info(
                    "[YEMEN SMS] OTP sent successfully to %s (purpose=%s, msg_id=%s)",
                    phone,
                    purpose,
                    msg_id,
                )
                return SMSResult(success=True, message_id=str(msg_id))
            else:
                logger.error(
                    "[YEMEN SMS] Failed response: HTTP %s",
                    response.status_code,
                )
                return SMSResult(
                    success=False,
                    error_message=f"HTTP {response.status_code}",
                )
        except requests.exceptions.Timeout:
            logger.error("[YEMEN SMS] Request timed out for phone %s", phone)
            return SMSResult(success=False, error_message="Connection timed out")
        except requests.exceptions.ConnectionError:
            logger.error("[YEMEN SMS] Connection error for phone %s", phone)
            return SMSResult(success=False, error_message="Connection error")
        except Exception as e:
            logger.exception("[YEMEN SMS] Unexpected error sending OTP")
            return SMSResult(success=False, error_message=str(e))
