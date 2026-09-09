from typing import Optional
from django.db.models import QuerySet, Count, Q
from apps.content.models import Summary, SummaryType, FlashcardDeck, Flashcard, ContentLink, LessonExplanation


def get_published_summaries(
    *,
    subject_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    lesson_id: Optional[str] = None,
) -> QuerySet[Summary]:
    """
    Returns published summaries ensuring parent lesson, unit, and subject are also published.
    """
    qs = Summary.objects.filter(status="published")

    if subject_id:
        qs = qs.filter(
            Q(subject_id=subject_id) |
            Q(lesson__unit__subject_id=subject_id) |
            Q(unit__subject_id=subject_id)
        )
    if unit_id:
        qs = qs.filter(
            Q(unit_id=unit_id) |
            Q(lesson__unit_id=unit_id)
        )
    if lesson_id:
        qs = qs.filter(lesson_id=lesson_id)

    # Parent status visibility checks
    qs = qs.filter(
        Q(lesson__isnull=True) | Q(lesson__status="published"),
        Q(unit__isnull=True) | Q(unit__status="published"),
        Q(subject__isnull=True) | Q(subject__status="published"),
    )

    return qs.distinct().order_by("sort_order", "-created_at")


def get_published_reader_summary(summary_id: str) -> Optional[Summary]:
    """Returns one published summary supported by the current reader."""
    summary = (
        Summary.objects.filter(
            id=summary_id,
            status="published",
            summary_type__in=[
                SummaryType.UNIT,
                SummaryType.LESSON,
                SummaryType.QUICK_REVIEW,
            ],
        )
        .select_related(
            "subject",
            "unit",
            "unit__subject",
            "lesson",
            "lesson__unit",
            "lesson__unit__subject",
        )
        .first()
    )
    if summary is None:
        return None
    if summary.summary_type == SummaryType.LESSON and summary.lesson_id is None:
        return None
    if summary.summary_type == SummaryType.UNIT and summary.lesson_id is not None:
        return None
    if summary.summary_type == SummaryType.QUICK_REVIEW and not (
        summary.lesson_id or summary.unit_id
    ):
        return None
    return summary


def get_published_flashcard_decks(
    *,
    subject_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    lesson_id: Optional[str] = None,
) -> QuerySet[FlashcardDeck]:
    """
    Returns published flashcard decks annotated with active cards_count (no N+1).
    """
    qs = FlashcardDeck.objects.filter(status="published")

    if subject_id:
        qs = qs.filter(
            Q(subject_id=subject_id) |
            Q(lesson__unit__subject_id=subject_id) |
            Q(unit__subject_id=subject_id)
        )
    if unit_id:
        qs = qs.filter(
            Q(unit_id=unit_id) |
            Q(lesson__unit_id=unit_id)
        )
    if lesson_id:
        qs = qs.filter(lesson_id=lesson_id)

    # Parent status visibility checks
    qs = qs.filter(
        Q(lesson__isnull=True) | Q(lesson__status="published"),
        Q(unit__isnull=True) | Q(unit__status="published"),
        Q(subject__isnull=True) | Q(subject__status="published"),
    )

    qs = qs.annotate(
        cards_count=Count("cards", filter=Q(cards__is_active=True))
    )

    return qs.distinct().order_by("sort_order", "-created_at")


def get_published_deck_cards(deck_id: str) -> QuerySet[Flashcard]:
    """
    Returns active cards for a published deck.
    """
    return Flashcard.objects.filter(
        deck_id=deck_id,
        is_active=True,
        deck__status="published",
    ).order_by("sort_order", "id")


def get_published_content_links(
    *,
    subject_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    lesson_id: Optional[str] = None,
) -> QuerySet[ContentLink]:
    """
    Returns published content links ensuring parent visibility.
    """
    qs = ContentLink.objects.filter(status="published")

    if subject_id:
        qs = qs.filter(
            Q(subject_id=subject_id) |
            Q(lesson__unit__subject_id=subject_id) |
            Q(unit__subject_id=subject_id)
        )
    if unit_id:
        qs = qs.filter(
            Q(unit_id=unit_id) |
            Q(lesson__unit_id=unit_id)
        )
    if lesson_id:
        qs = qs.filter(lesson_id=lesson_id)

    qs = qs.filter(
        Q(lesson__isnull=True) | Q(lesson__status="published"),
        Q(unit__isnull=True) | Q(unit__status="published"),
        Q(subject__isnull=True) | Q(subject__status="published"),
    )

    return qs.distinct().order_by("sort_order", "-created_at")


def get_published_lesson_explanation(lesson_id: str) -> Optional[LessonExplanation]:
    """
    Returns published explanation for a published lesson.
    """
    return LessonExplanation.objects.filter(
        lesson_id=lesson_id,
        status="published",
        lesson__status="published",
    ).select_related("lesson").first()
