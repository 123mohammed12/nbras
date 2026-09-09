import logging
from django.utils import timezone
from datetime import timedelta
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import StudyEnrollment
from apps.entitlements.services.access_service import check_resource_access
from apps.entitlements.registry import ResourceAccessRegistry
from apps.progress.models import LearningSession, SessionStatus

logger = logging.getLogger("progress.session_tracking")

MAX_HEARTBEAT_GAP_SECONDS = 300  # 5 minutes


def start_learning_session(
    *,
    user,
    resource_type: str,
    resource_id: str,
    client_session_id: str,
) -> LearningSession:
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
        raise ApplicationError("المورد غير متاح للاشتراك الحالي.", code="RESOURCE_ACCESS_DENIED")

    resource_data = ResourceAccessRegistry.resolve_resource(resource_type, resource_id)
    scope = resource_data.get("scope", {}) if resource_data else {}
    
    session, created = LearningSession.objects.get_or_create(
        user=user,
        client_session_id=client_session_id,
        defaults={
            "study_enrollment": enrollment,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "subject_id": scope.get("subject_id"),
            "unit_id": scope.get("unit_id"),
            "status": SessionStatus.ACTIVE,
            "started_at": timezone.now(),
            "last_heartbeat_at": timezone.now(),
        }
    )
    
    if not created and session.status == SessionStatus.ACTIVE:
        # Just update heartbeat if it exists and active
        session.last_heartbeat_at = timezone.now()
        session.save(update_fields=["last_heartbeat_at"])

    return session


def heartbeat_learning_session(
    *,
    user,
    client_session_id: str,
) -> LearningSession:
    session = LearningSession.objects.filter(user=user, client_session_id=client_session_id).first()
    if not session:
        raise ApplicationError("جلسة التعلم غير موجودة.", code="SESSION_NOT_FOUND")
        
    if session.status != SessionStatus.ACTIVE:
        return session
        
    now = timezone.now()
    gap = (now - session.last_heartbeat_at).total_seconds()
    
    if gap > 0 and gap <= MAX_HEARTBEAT_GAP_SECONDS:
        session.duration_seconds += int(gap)
    
    session.last_heartbeat_at = now
    session.save(update_fields=["last_heartbeat_at", "duration_seconds", "updated_at"])
    
    return session


def finish_learning_session(
    *,
    user,
    client_session_id: str,
) -> LearningSession:
    session = LearningSession.objects.filter(user=user, client_session_id=client_session_id).first()
    if not session:
        raise ApplicationError("جلسة التعلم غير موجودة.", code="SESSION_NOT_FOUND")
        
    if session.status != SessionStatus.ACTIVE:
        return session
        
    now = timezone.now()
    gap = (now - session.last_heartbeat_at).total_seconds()
    
    if gap > 0 and gap <= MAX_HEARTBEAT_GAP_SECONDS:
        session.duration_seconds += int(gap)
        
    session.status = SessionStatus.COMPLETED
    session.ended_at = now
    session.last_heartbeat_at = now
    session.save(update_fields=["status", "ended_at", "last_heartbeat_at", "duration_seconds", "updated_at"])
    
    # Update resource progress time if applicable
    from apps.progress.models import LearningResourceProgress
    res_progress = LearningResourceProgress.objects.filter(
        user=user,
        study_enrollment=session.study_enrollment,
        resource_type=session.resource_type,
        resource_id=session.resource_id,
    ).first()
    
    if res_progress:
        res_progress.time_spent_seconds += session.duration_seconds
        res_progress.save(update_fields=["time_spent_seconds"])
    
    return session
