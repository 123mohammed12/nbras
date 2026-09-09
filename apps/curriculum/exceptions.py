"""
Curriculum App Business Exceptions.

Inherit from apps.common.exceptions.ApplicationError for standardized error responses.
"""

from rest_framework import status as http_status
from apps.common.exceptions import ApplicationError


class InvalidGradeSectionError(ApplicationError):
    def __init__(self, message="القسم / المسار المحدد غير صالح لـهذا الصف الدراسي."):
        super().__init__(
            message=message,
            code="INVALID_GRADE_SECTION",
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )


class InvalidGradeTrackError(InvalidGradeSectionError):
    """Alias for backward compatibility."""
    pass


class ActiveEnrollmentExistsError(ApplicationError):
    def __init__(self, message="يوجد ملف دراسي نشط بالفعل لـهذا المستخدم."):
        super().__init__(
            message=message,
            code="ACTIVE_ENROLLMENT_EXISTS",
            status_code=http_status.HTTP_409_CONFLICT,
        )


class CurriculumNotFoundError(ApplicationError):
    def __init__(self, message="عنصر المنهج الدراسي غير موجود."):
        super().__init__(
            message=message,
            code="CURRICULUM_NOT_FOUND",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
