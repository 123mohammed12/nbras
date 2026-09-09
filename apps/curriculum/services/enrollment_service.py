"""
Study Enrollment Service.

Manages student enrollment creation, grade/section changes, and active enrollment state.
"""

import logging
from django.db import transaction
from django.utils import timezone

from apps.curriculum.exceptions import ActiveEnrollmentExistsError
from apps.curriculum.models import AcademicYear, StudyEnrollment
from apps.curriculum.validators import validate_and_get_grade_section

logger = logging.getLogger("curriculum.services")


@transaction.atomic
def create_study_enrollment(*, user, grade_id: str, section_id: str | None = None) -> StudyEnrollment:
    """
    Create a new active study enrollment for a user.

    - Uses select_for_update to prevent concurrent creation of two active enrollments.
    - Validates Grade & Section combination.
    """
    # Lock existing active enrollments for this user
    active_exists = (
        StudyEnrollment.objects.select_for_update(of=("self",))
        .filter(user=user, is_active=True)
        .exists()
    )
    if active_exists:
        raise ActiveEnrollmentExistsError("يوجد ملف دراسي نشط بالفعل لـهذا المستخدم.")

    grade, section = validate_and_get_grade_section(grade_id=grade_id, section_id=section_id)

    return StudyEnrollment.objects.create(
        user=user,
        grade=grade,
        section=section,
        academic_year=AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE).first(),
        status=StudyEnrollment.Status.ACTIVE,
        is_active=True,
    )


@transaction.atomic
def change_active_study_enrollment(
    *, user, new_grade_id: str, new_section_id: str | None = None
) -> tuple[StudyEnrollment, StudyEnrollment | None]:
    """
    Change user's active study enrollment:

    1. Deactivates existing active enrollment (marks status=CHANGED, is_active=False, ended_at=now).
    2. Validates new Grade & Section.
    3. Creates new active enrollment.
    4. Preserves historical attempt/progress records bound to the old enrollment.
    """
    old_enrollment = (
        StudyEnrollment.objects.select_for_update(of=("self",))
        .filter(user=user, is_active=True)
        .first()
    )

    if old_enrollment:
        old_enrollment.is_active = False
        old_enrollment.status = StudyEnrollment.Status.CHANGED
        old_enrollment.ended_at = timezone.now()
        old_enrollment.save(update_fields=["is_active", "status", "ended_at", "updated_at"])

    grade, section = validate_and_get_grade_section(
        grade_id=new_grade_id, section_id=new_section_id
    )

    new_enrollment = StudyEnrollment.objects.create(
        user=user,
        grade=grade,
        section=section,
        academic_year=AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE).first(),
        status=StudyEnrollment.Status.ACTIVE,
        is_active=True,
    )

    return new_enrollment, old_enrollment
