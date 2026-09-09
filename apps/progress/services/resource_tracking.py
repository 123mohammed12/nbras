import logging
import math
from django.utils import timezone
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import StudyEnrollment
from apps.entitlements.services.access_service import check_resource_access
from apps.entitlements.registry import ResourceAccessRegistry
from apps.progress.models import LearningResourceProgress, ProgressStatus

logger = logging.getLogger("progress.resource_tracking")


def update_learning_resource_progress(
    *,
    user,
    resource_type: str,
    resource_id: str,
    completion_percentage: float,
    last_position: float,
    client_event_id: str | None = None,
) -> LearningResourceProgress:
    """Store the latest absolute reading state without completing parents."""
    if not math.isfinite(completion_percentage) or not 0 <= completion_percentage <= 100:
        raise ApplicationError(
            "نسبة التقدم غير صالحة.", code="INVALID_PROGRESS", status_code=400
        )
    if not math.isfinite(last_position) or not 0 <= last_position <= 1:
        raise ApplicationError(
            "موضع القراءة غير صالح.", code="INVALID_READING_POSITION", status_code=400
        )

    enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
    if not enrollment:
        raise ApplicationError(
            "لا يوجد ملف دراسي نشط للمستخدم.", code="NO_ACTIVE_ENROLLMENT"
        )

    decision = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise ApplicationError(
            "المورد غير متاح للاشتراك الحالي.",
            code="RESOURCE_ACCESS_DENIED",
            status_code=403,
        )

    resource_data = ResourceAccessRegistry.resolve_resource(resource_type, resource_id)
    if not resource_data:
        raise ApplicationError("المورد غير موجود.", code="RESOURCE_NOT_FOUND")

    scope = resource_data.get("scope", {})
    now = timezone.now()
    progress, _ = LearningResourceProgress.objects.get_or_create(
        user=user,
        study_enrollment=enrollment,
        resource_type=resource_type,
        resource_id=resource_id,
        defaults={
            "subject_id": scope.get("subject_id"),
            "unit_id": scope.get("unit_id"),
            "lesson_id": scope.get("lesson_id"),
            "status": ProgressStatus.IN_PROGRESS,
            "started_at": now,
        },
    )
    snapshot = dict(progress.resource_snapshot or {})
    if client_event_id and snapshot.get("last_client_event_id") == client_event_id:
        return progress

    incoming = float(completion_percentage)
    is_completed = progress.status == ProgressStatus.COMPLETED or incoming >= 100
    progress.status = (
        ProgressStatus.COMPLETED if is_completed else ProgressStatus.IN_PROGRESS
    )
    progress.completion_percentage = max(
        float(progress.completion_percentage), incoming
    )
    if progress.started_at is None:
        progress.started_at = now
    progress.last_activity_at = now
    if is_completed and progress.completed_at is None:
        progress.completed_at = now
    snapshot["last_position"] = float(last_position)
    if client_event_id:
        snapshot["last_client_event_id"] = client_event_id
    progress.resource_snapshot = snapshot
    progress.source_version = str(resource_data.get("version") or "")
    progress.save(
        update_fields=[
            "status",
            "completion_percentage",
            "started_at",
            "last_activity_at",
            "completed_at",
            "resource_snapshot",
            "source_version",
            "updated_at",
        ]
    )
    return progress


def start_learning_resource(
    *,
    user,
    resource_type: str,
    resource_id: str,
    client_event_id: str | None = None,
) -> LearningResourceProgress:
    """
    Marks a learning resource as started for the active enrollment.
    """
    enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
    if not enrollment:
        raise ApplicationError("لا يوجد ملف دراسي نشط للمستخدم.", code="NO_ACTIVE_ENROLLMENT")

    decision = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise ApplicationError("المورد غير متاح للاشتراك الحالي.", code="RESOURCE_ACCESS_DENIED", status_code=403)

    resource_data = ResourceAccessRegistry.resolve_resource(resource_type, resource_id)
    if not resource_data:
        raise ApplicationError("المورد غير موجود.", code="RESOURCE_NOT_FOUND")

    scope = resource_data.get("scope", {})
    subject_id = scope.get("subject_id")
    unit_id = scope.get("unit_id")
    lesson_id = scope.get("lesson_id")

    progress, created = LearningResourceProgress.objects.get_or_create(
        user=user,
        study_enrollment=enrollment,
        resource_type=resource_type,
        resource_id=resource_id,
        defaults={
            "subject_id": subject_id,
            "unit_id": unit_id,
            "lesson_id": lesson_id,
            "status": ProgressStatus.IN_PROGRESS,
            "started_at": timezone.now(),
            "last_activity_at": timezone.now(),
        }
    )

    if not created and progress.status == ProgressStatus.NOT_STARTED:
        progress.status = ProgressStatus.IN_PROGRESS
        progress.started_at = timezone.now()
        progress.last_activity_at = timezone.now()
        progress.save(update_fields=["status", "started_at", "last_activity_at", "updated_at"])

    return progress


def complete_learning_resource(
    *,
    user,
    resource_type: str,
    resource_id: str,
    client_event_id: str | None = None,
) -> LearningResourceProgress:
    """
    Marks a learning resource as completed. (Idempotent)
    Triggers recalculation of parents (Lesson, Unit, Subject).
    """
    enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
    if not enrollment:
        raise ApplicationError("لا يوجد ملف دراسي نشط للمستخدم.", code="NO_ACTIVE_ENROLLMENT")

    decision = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise ApplicationError("المورد غير متاح للاشتراك الحالي.", code="RESOURCE_ACCESS_DENIED", status_code=403)

    resource_data = ResourceAccessRegistry.resolve_resource(resource_type, resource_id)
    if not resource_data:
        raise ApplicationError("المورد غير موجود.", code="RESOURCE_NOT_FOUND")

    scope = resource_data.get("scope", {})
    subject_id = scope.get("subject_id")
    unit_id = scope.get("unit_id")
    lesson_id = scope.get("lesson_id")

    progress, created = LearningResourceProgress.objects.get_or_create(
        user=user,
        study_enrollment=enrollment,
        resource_type=resource_type,
        resource_id=resource_id,
        defaults={
            "subject_id": subject_id,
            "unit_id": unit_id,
            "lesson_id": lesson_id,
            "status": ProgressStatus.COMPLETED,
            "completion_percentage": 100.0,
            "started_at": timezone.now(),
            "last_activity_at": timezone.now(),
            "completed_at": timezone.now(),
        }
    )

    if not created and progress.status != ProgressStatus.COMPLETED:
        progress.status = ProgressStatus.COMPLETED
        progress.completion_percentage = 100.0
        progress.completed_at = timezone.now()
        progress.last_activity_at = timezone.now()
        progress.save(update_fields=["status", "completion_percentage", "completed_at", "last_activity_at", "updated_at"])
    
    # Only primary lesson content contributes to parent completion. Summary,
    # quick review, decks, and assessments keep independent resource progress.
    from apps.progress.services.recalculation import (
        recalculate_lesson_progress,
        recalculate_unit_progress,
        recalculate_subject_progress,
    )
    if resource_type == "lesson_explanation" and lesson_id:
        recalculate_lesson_progress(
            user=user,
            enrollment=enrollment,
            lesson_id=lesson_id,
        )
        recalculate_unit_progress(user=user, enrollment=enrollment, unit_id=unit_id)
    elif resource_type == "lesson_explanation" and unit_id:
        recalculate_unit_progress(user=user, enrollment=enrollment, unit_id=unit_id)
    elif resource_type == "lesson_explanation" and subject_id:
        recalculate_subject_progress(user=user, enrollment=enrollment, subject_id=subject_id)

    return progress
