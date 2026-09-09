"""
Account-specific business exceptions.

All exceptions inherit from apps.common.exceptions.ApplicationError
so they integrate with the standardized error response envelope.
"""

from rest_framework import status as http_status

from apps.common.exceptions import ApplicationError


# ─── OTP Errors ───────────────────────────────────────

class InvalidOTPError(ApplicationError):
    def __init__(self, message="رمز التحقق غير صحيح."):
        super().__init__(message=message, code="INVALID_OTP")


class OTPExpiredError(ApplicationError):
    def __init__(self, message="انتهت صلاحية رمز التحقق."):
        super().__init__(message=message, code="OTP_EXPIRED")


class OTPAttemptsExceededError(ApplicationError):
    def __init__(self, message="تم تجاوز عدد المحاولات المسموح بها."):
        super().__init__(message=message, code="OTP_ATTEMPTS_EXCEEDED")


class OTPCooldownError(ApplicationError):
    def __init__(self, remaining_seconds: int = 60):
        super().__init__(
            message=f"يرجى الانتظار {remaining_seconds} ثانية قبل إعادة الإرسال.",
            code="OTP_COOLDOWN",
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
        )


# ─── Phone Errors ─────────────────────────────────────

class PhoneAlreadyExistsError(ApplicationError):
    def __init__(self, message="رقم الهاتف مسجل بالفعل."):
        super().__init__(message=message, code="PHONE_ALREADY_EXISTS", status_code=http_status.HTTP_409_CONFLICT)


class InvalidPhoneError(ApplicationError):
    def __init__(self, message="رقم الهاتف غير صالح."):
        super().__init__(message=message, code="INVALID_PHONE")


# ─── Session Errors ──────────────────────────────────

class SessionRevokedError(ApplicationError):
    def __init__(self, message="الجلسة ملغاة."):
        super().__init__(message=message, code="SESSION_REVOKED", status_code=http_status.HTTP_401_UNAUTHORIZED)


class InvalidRefreshTokenError(ApplicationError):
    def __init__(self, message="رمز التحديث غير صالح أو منتهي الصلاحية."):
        super().__init__(message=message, code="INVALID_REFRESH_TOKEN", status_code=http_status.HTTP_401_UNAUTHORIZED)


# ─── Merge Errors ─────────────────────────────────────

class MergeInProgressError(ApplicationError):
    def __init__(self, message="عملية دمج الحساب قيد التنفيذ بالفعل."):
        super().__init__(message=message, code="MERGE_IN_PROGRESS", status_code=http_status.HTTP_409_CONFLICT)


class MergeFailedError(ApplicationError):
    def __init__(self, message="فشلت عملية دمج الحساب."):
        super().__init__(message=message, code="MERGE_FAILED", status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─── Auth Errors ──────────────────────────────────────

class AccountNotFoundError(ApplicationError):
    def __init__(self, message="الحساب غير موجود."):
        super().__init__(message=message, code="ACCOUNT_NOT_FOUND", status_code=http_status.HTTP_404_NOT_FOUND)


class AccountInactiveError(ApplicationError):
    def __init__(self, message="الحساب غير نشط."):
        super().__init__(message=message, code="ACCOUNT_INACTIVE", status_code=http_status.HTTP_403_FORBIDDEN)


class AlreadyRegisteredError(ApplicationError):
    def __init__(self, message="هذا الحساب مسجل بالفعل."):
        super().__init__(message=message, code="ALREADY_REGISTERED", status_code=http_status.HTTP_409_CONFLICT)


class InvalidCredentialsError(ApplicationError):
    def __init__(self, message="بيانات الدخول غير صحيحة."):
        super().__init__(message=message, code="INVALID_CREDENTIALS", status_code=http_status.HTTP_400_BAD_REQUEST)


class InvalidPasswordError(ApplicationError):
    def __init__(self, message="كلمة المرور الحالية غير صحيحة."):
        super().__init__(message=message, code="INVALID_CURRENT_PASSWORD", status_code=http_status.HTTP_400_BAD_REQUEST)


class PasswordMismatchError(ApplicationError):
    def __init__(self, message="كلمتا المرور غير متطابقتين."):
        super().__init__(message=message, code="PASSWORD_MISMATCH", status_code=http_status.HTTP_400_BAD_REQUEST)


# ─── Verification Grant Errors ────────────────────────

class VerificationGrantError(ApplicationError):
    def __init__(self, message="إثبات التحقق غير صالح أو منتهي الصلاحية."):
        super().__init__(message=message, code="INVALID_VERIFICATION_GRANT")


# ─── Password Reset Errors ────────────────────────────

class InvalidPasswordResetProofError(ApplicationError):
    """Generic error for password reset failures — prevents account enumeration."""
    def __init__(self, message="بيانات إعادة تعيين كلمة المرور غير صالحة."):
        super().__init__(message=message, code="INVALID_PASSWORD_RESET_PROOF")


# ─── Installation ID Errors ──────────────────────────

class InstallationIdMismatchError(ApplicationError):
    def __init__(self, message="معرف التثبيت في الهيدر لا يتطابق مع الجسم."):
        super().__init__(message=message, code="INSTALLATION_ID_MISMATCH")


class InstallationIdRequiredError(ApplicationError):
    def __init__(self, message="معرف التثبيت مطلوب."):
        super().__init__(message=message, code="INSTALLATION_ID_REQUIRED")
