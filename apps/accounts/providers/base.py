"""
OTP Provider Abstract Interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SMSResult:
    success: bool
    message_id: str | None = None
    error_message: str | None = None


class OTPProvider(ABC):
    """
    Abstract interface for sending SMS OTP codes.
    Allows swapping SMS gateways without touching business logic.
    """

    @abstractmethod
    def send_otp(self, phone: str, code: str, purpose: str) -> SMSResult:
        """
        Send an OTP code to a phone number.

        Args:
            phone: Normalized phone number (+9677XXXXXXXX).
            code: Plaintext OTP code.
            purpose: Reason for OTP (register, login, etc.).

        Returns:
            SMSResult object.
        """
        pass
