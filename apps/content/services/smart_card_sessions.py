from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.common.exceptions import ApplicationError
from apps.content.models import Flashcard, FlashcardDeck
from apps.curriculum.models import StudyEnrollment
from apps.entitlements.services.access_service import check_resource_access
from apps.progress.models import (
    LearningResourceProgress,
    LearningSession,
    ProgressStatus,
    SessionStatus,
    SmartCardRating,
    SmartCardReview,
)


SOURCE_TYPE = "flashcard_deck"
ALLOWED_REVIEW_ACTIONS = [
    {"value": SmartCardRating.AGAIN, "label": "تحتاج مراجعة"},
    {"value": SmartCardRating.HARD, "label": "بصعوبة"},
    {"value": SmartCardRating.GOOD, "label": "عرفتها"},
]


def _active_enrollment(user):
    enrollment = (
        StudyEnrollment.objects.filter(user=user, is_active=True)
        .select_related("grade", "section")
        .first()
    )
    if enrollment is None:
        raise ApplicationError(
            "لا يوجد ملف دراسي نشط للمستخدم.",
            code="NO_ACTIVE_ENROLLMENT",
            status_code=403,
        )
    return enrollment


def _published_deck(deck_id):
    deck = (
        FlashcardDeck.objects.filter(
            id=deck_id,
            status="published",
            lesson__status="published",
            lesson__unit__status="published",
            lesson__unit__subject__status="published",
        )
        .select_related("subject", "unit", "lesson", "lesson__unit")
        .first()
    )
    if deck is None:
        raise ApplicationError(
            "حزمة البطاقات غير موجودة أو غير منشورة.",
            code="SMART_CARD_DECK_NOT_FOUND",
            status_code=404,
        )
    return deck


@transaction.atomic
def start_or_resume_smart_card_session(*, user, deck_id: str, client_session_id: str):
    enrollment = _active_enrollment(user)
    # Locking the enrollment serializes competing start requests for the same user.
    StudyEnrollment.objects.select_for_update().get(pk=enrollment.pk)
    deck = _published_deck(deck_id)
    decision = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type=SOURCE_TYPE,
        resource_id=str(deck.id),
    )
    if not decision.allowed:
        raise ApplicationError(
            "ليس لديك صلاحية للوصول إلى حزمة البطاقات.",
            code=decision.reason_code,
            status_code=403,
        )

    cards = list(
        Flashcard.objects.filter(deck=deck, is_active=True).order_by("sort_order", "id")
    )
    if not cards:
        raise ApplicationError(
            "لا توجد بطاقات فعالة في هذه الحزمة.",
            code="SMART_CARD_DECK_EMPTY",
            status_code=409,
        )

    session = (
        LearningSession.objects.filter(
            user=user,
            study_enrollment=enrollment,
            resource_type=SOURCE_TYPE,
            resource_id=str(deck.id),
            status=SessionStatus.ACTIVE,
        )
        .order_by("-last_heartbeat_at")
        .first()
    )
    if session is None:
        session = LearningSession.objects.create(
            user=user,
            study_enrollment=enrollment,
            client_session_id=client_session_id,
            resource_type=SOURCE_TYPE,
            resource_id=str(deck.id),
            subject_id=deck.subject_id,
            unit_id=deck.unit_id,
            lesson_id=deck.lesson_id,
            total_items=len(cards),
            current_position=0,
            session_state={"ordered_card_ids": [str(card.id) for card in cards]},
        )
    else:
        session.last_heartbeat_at = timezone.now()
        session.save(update_fields=["last_heartbeat_at", "updated_at"])

    return session, deck, cards, decision


@transaction.atomic
def review_smart_card(
    *,
    user,
    session_id: str,
    card_id: str,
    rating: str,
    client_event_id: str,
    reviewed_at: datetime | None = None,
):
    session = (
        LearningSession.objects.select_for_update()
        .filter(id=session_id, user=user, resource_type=SOURCE_TYPE)
        .first()
    )
    if session is None:
        raise ApplicationError(
            "جلسة البطاقات غير موجودة.",
            code="SMART_CARD_SESSION_NOT_FOUND",
            status_code=404,
        )

    existing = SmartCardReview.objects.filter(
        session=session, client_event_id=client_event_id
    ).first()
    if existing is not None:
        return session, existing, True

    if session.status != SessionStatus.ACTIVE:
        raise ApplicationError(
            "جلسة البطاقات مكتملة.",
            code="SMART_CARD_SESSION_COMPLETED",
            status_code=409,
        )
    if rating not in SmartCardRating.values:
        raise ApplicationError(
            "تقييم البطاقة غير صالح.",
            code="INVALID_SMART_CARD_RATING",
            status_code=400,
        )

    ordered_ids = list((session.session_state or {}).get("ordered_card_ids") or [])
    if session.current_position >= len(ordered_ids):
        raise ApplicationError(
            "لا توجد بطاقة حالية في الجلسة.",
            code="SMART_CARD_POSITION_INVALID",
            status_code=409,
        )
    if str(ordered_ids[session.current_position]) != str(card_id):
        raise ApplicationError(
            "البطاقة لا تطابق موضع الجلسة الحالي.",
            code="SMART_CARD_OUT_OF_ORDER",
            status_code=409,
        )

    card = Flashcard.objects.filter(id=card_id, deck_id=session.resource_id).first()
    if card is None:
        raise ApplicationError(
            "البطاقة غير موجودة ضمن الحزمة الحالية.",
            code="SMART_CARD_NOT_IN_SESSION",
            status_code=404,
        )

    review = SmartCardReview.objects.create(
        session=session,
        card=card,
        rating=rating,
        client_event_id=client_event_id,
        reviewed_at=reviewed_at or timezone.now(),
    )
    session.current_position += 1
    session.last_heartbeat_at = timezone.now()
    if session.current_position >= session.total_items:
        session.status = SessionStatus.COMPLETED
        session.ended_at = timezone.now()
    session.save(
        update_fields=[
            "current_position",
            "status",
            "ended_at",
            "last_heartbeat_at",
            "updated_at",
        ]
    )
    _update_deck_progress(session)
    return session, review, False


def _update_deck_progress(session):
    reviewed_count = session.smart_card_reviews.count()
    percentage = (reviewed_count / session.total_items * 100) if session.total_items else 0
    rating_counts = {
        row["rating"]: row["count"]
        for row in session.smart_card_reviews.values("rating").annotate(count=Count("id"))
    }
    now = timezone.now()
    progress, _ = LearningResourceProgress.objects.get_or_create(
        user=session.user,
        study_enrollment=session.study_enrollment,
        resource_type=SOURCE_TYPE,
        resource_id=session.resource_id,
        defaults={
            "subject_id": session.subject_id,
            "unit_id": session.unit_id,
            "lesson_id": session.lesson_id,
            "started_at": session.started_at,
        },
    )
    progress.status = (
        ProgressStatus.COMPLETED
        if session.status == SessionStatus.COMPLETED
        else ProgressStatus.IN_PROGRESS
    )
    progress.completion_percentage = percentage
    progress.started_at = progress.started_at or session.started_at
    progress.last_activity_at = now
    progress.completed_at = now if session.status == SessionStatus.COMPLETED else None
    progress.resource_snapshot = {
        **(progress.resource_snapshot or {}),
        "reviewed_count": reviewed_count,
        "rating_counts": rating_counts,
        "last_session_id": str(session.id),
    }
    progress.save(
        update_fields=[
            "status",
            "completion_percentage",
            "started_at",
            "last_activity_at",
            "completed_at",
            "resource_snapshot",
            "updated_at",
        ]
    )


def rating_counts_for(session):
    return {
        row["rating"]: row["count"]
        for row in session.smart_card_reviews.values("rating").annotate(count=Count("id"))
    }
