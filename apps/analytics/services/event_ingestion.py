import logging
import uuid
from decimal import Decimal
from django.utils import timezone
from apps.common.exceptions import ApplicationError
from apps.analytics.models import AnalyticsEvent, DailyLearningSummary

logger = logging.getLogger("analytics.event_ingestion")

PROHIBITED_PAYLOAD_KEYS = {
    "phone", "phone_number", "full_name", "name", "school", "governorate",
    "district", "isolation", "token", "access_token", "refresh_token",
    "authorization", "password", "otp", "verification_code", "activation_code",
    "raw_code", "code_hash", "raw_answer", "answer_text", "essay_response",
    "essay_content", "authorization_header", "cookie", "session_key", "ip",
    "ip_address", "storage_path", "file_path", "media_path",
}

EVENT_SCHEMAS = {
    "content_started": {
        "allowed_fields": {"resource_type", "resource_id", "client_event_id"},
        "required_fields": {"resource_type", "resource_id"},
        "server_only": False,
    },
    "content_completed": {
        "allowed_fields": {"resource_type", "resource_id", "time_spent_seconds", "client_event_id"},
        "required_fields": {"resource_type", "resource_id"},
        "server_only": False,
    },
    "learning_session_started": {
        "allowed_fields": {"resource_type", "resource_id", "client_session_id"},
        "required_fields": {"client_session_id"},
        "server_only": False,
    },
    "learning_session_completed": {
        "allowed_fields": {"client_session_id", "duration_seconds", "heartbeats_count"},
        "required_fields": {"client_session_id", "duration_seconds"},
        "server_only": False,
    },
    "assessment_started": {
        "allowed_fields": {"assessment_id", "attempt_id", "assessment_type"},
        "required_fields": {"assessment_id"},
        "server_only": True,
    },
    "assessment_submitted": {
        "allowed_fields": {
            "assessment_id", "attempt_id", "score", "maximum_score",
            "answered_count", "correct_count", "time_spent_seconds"
        },
        "required_fields": {"assessment_id", "attempt_id", "score"},
        "server_only": True,
    },
    "assessment_reviewed": {
        "allowed_fields": {"assessment_id", "attempt_id", "review_mode"},
        "required_fields": {"assessment_id", "attempt_id"},
        "server_only": False,
    },
    "subscription_activated": {
        "allowed_fields": {"subscription_id", "plan_id", "activated_at"},
        "required_fields": {"subscription_id", "plan_id"},
        "server_only": True,
    },
    "guest_merged": {
        "allowed_fields": {"guest_user_id", "merged_at", "events_count", "progress_count"},
        "required_fields": {"guest_user_id"},
        "server_only": True,
    },
}


def contains_prohibited_key(data) -> bool:
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).lower() in PROHIBITED_PAYLOAD_KEYS:
                return True
            if contains_prohibited_key(v):
                return True
    elif isinstance(data, list):
        for item in data:
            if contains_prohibited_key(item):
                return True
    return False


def validate_event_payload(*, event_type: str, payload: dict, source_type: str = ""):
    if contains_prohibited_key(payload):
        raise ApplicationError("Analytics event payload contains prohibited key", code="PROHIBITED_KEY", status_code=400)

    schema = EVENT_SCHEMAS.get(event_type)
    if schema:
        if schema.get("server_only") and source_type.lower() not in ["server", "system", "internal"]:
            raise ApplicationError(f"Event type '{event_type}' is server-only", code="SERVER_ONLY_EVENT", status_code=403)

        allowed = schema["allowed_fields"]
        for k in payload.keys():
            if k not in allowed:
                raise ApplicationError(f"Payload field '{k}' is not allowed for event '{event_type}'", code="INVALID_PAYLOAD_FIELD", status_code=400)

        required = schema.get("required_fields", set())
        for r in required:
            if r not in payload:
                raise ApplicationError(f"Missing required field '{r}' for event '{event_type}'", code="MISSING_REQUIRED_FIELD", status_code=400)



def ingest_analytics_event(
    *,
    user,
    enrollment,
    event_type: str,
    event_id: str | None = None,
    source_type: str = "",
    source_id: str = "",
    attempt=None,
    subject=None,
    unit=None,
    lesson=None,
    payload: dict | None = None,
) -> AnalyticsEvent:
    if not event_id:
        event_id = str(uuid.uuid4())
        
    payload = payload or {}
    
    validate_event_payload(event_type=event_type, payload=payload, source_type=source_type)

    event, created = AnalyticsEvent.objects.get_or_create(
        event_id=event_id,
        defaults={
            "user": user,
            "study_enrollment": enrollment,
            "event_type": event_type,
            "source_type": source_type,
            "source_id": source_id,
            "attempt": attempt,
            "subject": subject,
            "unit": unit,
            "lesson": lesson,
            "occurred_at": timezone.now(),
            "payload": payload,
        }
    )
    
    if created:
        update_daily_summary(user=user, enrollment=enrollment, event=event)
        
    return event


def update_daily_summary(*, user, enrollment, event: AnalyticsEvent):
    today = event.occurred_at.date()
    
    targets = [None]
    if event.subject:
        targets.append(event.subject)
        
    for subj in targets:
        summary, _ = DailyLearningSummary.objects.get_or_create(
            user=user,
            study_enrollment=enrollment,
            date=today,
            subject=subj,
        )
        
        if event.event_type == "learning_session_completed":
            dur = event.payload.get("duration_seconds", 0)
            summary.learning_seconds += int(dur)
            
        elif event.event_type == "content_started":
            summary.resources_started += 1
            
        elif event.event_type == "content_completed":
            summary.resources_completed += 1
            
        elif event.event_type == "assessment_submitted":
            summary.attempts_submitted += 1
            ans_c = event.payload.get("answered_count", 0)
            corr_c = event.payload.get("correct_count", 0)
            pts_e = event.payload.get("score", 0)
            pts_m = event.payload.get("maximum_score", 0)
            
            summary.questions_answered += int(ans_c)
            summary.correct_answers += int(corr_c)
            summary.points_earned = Decimal(str(summary.points_earned)) + Decimal(str(pts_e))
            summary.points_possible = Decimal(str(summary.points_possible)) + Decimal(str(pts_m))
            
        summary.save()

