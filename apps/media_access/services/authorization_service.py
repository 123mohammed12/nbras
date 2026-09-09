from typing import Tuple, Optional
from django.db.models import Model
from apps.curriculum.models import StudyEnrollment

from apps.entitlements.services.access_service import check_resource_access


def authorize_media_access(
    *,
    user,
    resource: Model,
    definition_model_name: str,
) -> Tuple[bool, str]:
    """
    Authorizes a user to access a specific media resource.
    Returns: (is_authorized: bool, reason: str)
    """
    if not user or not user.is_authenticated:
        return False, "unauthenticated"

    # Staff users have admin access
    if user.is_staff or getattr(user, "is_superuser", False):
        return True, "staff_access"

    # Determine publication status of the resource itself
    resource_status = getattr(resource, "status", None)
    if resource_status and resource_status != "published":
        return False, "resource_not_published"

    is_active = getattr(resource, "is_active", True)
    if not is_active:
        return False, "resource_inactive"

    # Extract parent lesson, unit, subject
    lesson = getattr(resource, "lesson", None)
    unit = getattr(resource, "unit", None)
    subject = getattr(resource, "subject", None)

    if definition_model_name == "Flashcard":
        deck = getattr(resource, "deck", None)
        if deck:
            if deck.status != "published":
                return False, "deck_not_published"
            lesson = lesson or deck.lesson
            unit = unit or deck.unit
            subject = subject or deck.subject

    if definition_model_name in ["QuestionAsset", "QuestionOption"]:
        q_ver = getattr(resource, "question_version", None)
        if q_ver:
            q = getattr(q_ver, "question", None)
            if q:
                if q.status != "published":
                    return False, "question_not_published"
                lesson = lesson or q.lesson
                unit = unit or q.unit
                subject = subject or q.subject

    if definition_model_name == "MinisterialExamItem":
        m_exam = getattr(resource, "ministerial_exam", None)
        if m_exam:
            if m_exam.status != "published":
                return False, "exam_not_published"
            subject = subject or m_exam.subject


    # Infer parent unit/subject from lesson if missing
    if lesson:
        if lesson.status != "published":
            return False, "lesson_not_published"
        unit = unit or lesson.unit
        subject = subject or (lesson.unit.subject if lesson.unit else None)

    if unit:
        if unit.status != "published":
            return False, "unit_not_published"
        subject = subject or unit.subject

    if subject:
        if subject.status != "published":
            return False, "subject_not_published"

    # Check active StudyEnrollment
    active_enrollment = StudyEnrollment.objects.filter(
        user=user,
        is_active=True,
    ).first()

    if not active_enrollment:
        return False, "enrollment_required"

    # Check Grade and Section alignment
    target_grade = None
    target_section = None
    if subject:
        target_grade = subject.grade
        target_section = subject.section
    elif unit and unit.subject:
        target_grade = unit.subject.grade
        target_section = unit.subject.section

    if target_grade and active_enrollment.grade_id != target_grade.id:
        return False, "grade_mismatch"

    if target_section and active_enrollment.section_id != target_section.id:
        return False, "section_mismatch"

    # Authorize the actual content parent, including subject-level resources.
    # A missing unit must never mean unrestricted media access.
    canonical_types = {
        "Summary": "summary", "Flashcard": "flashcard",
        "ContentLink": "content_link", "MinisterialExam": "ministerial_exam",
    }
    target_type = canonical_types.get(definition_model_name)
    target_id = str(resource.pk) if target_type else None
    if definition_model_name == "MinisterialExamItem":
        target_type, target_id = "ministerial_exam", str(resource.ministerial_exam_id)
    elif not target_type and lesson:
        target_type, target_id = "lesson", str(lesson.pk)
    elif not target_type and unit:
        target_type, target_id = "unit", str(unit.pk)
    elif not target_type and subject:
        target_type, target_id = "subject", str(subject.pk)
    if target_type and target_id:
        access_result = check_resource_access(
            user=user,
            enrollment=active_enrollment,
            resource_type=target_type,
            resource_id=target_id,
        )
        if not access_result.allowed:
            if access_result.reason_code == "ACADEMIC_CONTEXT_MISMATCH":
                return False, "grade_mismatch"
            if access_result.reason_code in {
                "SUBSCRIPTION_REQUIRED", "SUBJECT_NOT_INCLUDED",
            }:
                return False, "subscription_required"
            if access_result.reason_code == "SUBSCRIPTION_EXPIRED":
                return False, "subscription_expired"
            return False, access_result.reason_code.lower()

        return True, "authorized"
    return False, "unresolved_media_scope"
