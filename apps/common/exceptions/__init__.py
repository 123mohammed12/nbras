"""
Application-level business exceptions with error codes.

Base ApplicationError and common cross-cutting exceptions.
Domain-specific exceptions live in apps.<app_name>.exceptions.
"""

from rest_framework import status as http_status


class ApplicationError(Exception):
    """Base class for all application-level errors."""

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = http_status.HTTP_400_BAD_REQUEST,
        fields: dict | None = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.fields = fields
        super().__init__(message)


# ─── Location Errors ─────────────────────────────────

class InvalidLocationRelationError(ApplicationError):
    def __init__(self, message="العلاقة الجغرافية غير متوافقة."):
        super().__init__(message=message, code="INVALID_LOCATION_RELATION")


# ─── Idempotency Errors ──────────────────────────────

class DuplicateRequestError(ApplicationError):
    def __init__(self, message="تم معالجة هذا الطلب سابقاً."):
        super().__init__(
            message=message,
            code="DUPLICATE_REQUEST",
            status_code=http_status.HTTP_409_CONFLICT,
        )
