"""
Curriculum Selectors.

Provides optimized, read-only querysets for curriculum entities.
"""

from django.db.models import QuerySet
from apps.curriculum.models import Grade, Section, Subject, Unit, Lesson, ContentStatus


def get_active_grades() -> QuerySet[Grade]:
    return Grade.objects.filter(is_active=True).prefetch_related("sections").order_by("sort_order", "id")


def get_grade_sections(grade_id: str) -> QuerySet[Section]:
    return Section.objects.filter(grade_id=grade_id, is_active=True).order_by("sort_order", "id")


def get_user_subjects(*, grade_id: str | None = None, section_id: str | None = None) -> QuerySet[Subject]:
    """
    Get published subjects for a specific grade and section.
    If grade_id is not specified, returns an empty queryset (requires study selection).
    """
    if not grade_id:
        return Subject.objects.none()

    qs = Subject.objects.filter(grade_id=grade_id, status=ContentStatus.PUBLISHED)
    if section_id:
        qs = qs.filter(section_id=section_id)

    return qs.select_related("grade", "section").order_by("sort_order", "id")


def get_subject_units(subject_id: str) -> QuerySet[Unit]:
    return (
        Unit.objects.filter(
            subject_id=subject_id,
            status=ContentStatus.PUBLISHED,
        )
        .select_related("subject", "term")
        .prefetch_related("lessons")
        .order_by("sort_order", "id")
    )


def get_unit_lessons(unit_id: str) -> QuerySet[Lesson]:
    return (
        Lesson.objects.filter(
            unit_id=unit_id,
            status=ContentStatus.PUBLISHED,
        )
        .select_related("unit")
        .order_by("sort_order", "id")
    )
