from django.conf import settings
from django.db.models import Avg, Count, Exists, OuterRef, Q

from apps.assessments.models import Assessment, AssessmentType, TrainingBatchScope
from apps.assessments.services.training import training_batch_cards
from apps.attempts.models import AssessmentAttempt, AttemptStatus
from apps.content.models import FlashcardDeck, Summary, SummaryType
from apps.curriculum.models import ContentStatus, Lesson, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import AccessContext, check_resource_access
from apps.ministerial_exams.models import MinisterialExamItem
from apps.ministerial_exams.services import (
    balanced_part_sizes,
    ministerial_coverage_count,
)
from apps.progress.models import LearningResourceProgress, LessonProgress, UnitProgress
from apps.question_bank.models import SourceType


_COMPLETED_ATTEMPT_STATUSES = {
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
}
_DYNAMIC_UNIT_MINISTERIAL_MARKER = "dynamic-source:unit_ministerial"


def _iso(value):
    return value.isoformat() if value else None


def get_unit_center(*, user, subject_id: str, unit_id: str):
    """Build the unit-center read model from the existing curriculum systems."""
    enrollment = (
        StudyEnrollment.objects.filter(user=user, is_active=True)
        .select_related("grade", "section")
        .first()
    )
    if enrollment is None:
        return None, "enrollment"

    subject = Subject.objects.filter(
        id=subject_id,
        grade_id=enrollment.grade_id,
        section_id=enrollment.section_id,
        status=ContentStatus.PUBLISHED,
    ).first()
    if subject is None:
        return None, "subject"

    unit = Unit.objects.filter(
        id=unit_id,
        subject=subject,
        status=ContentStatus.PUBLISHED,
    ).first()
    if unit is None:
        return None, "unit"

    access = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type="unit",
        resource_id=str(unit.id),
        context=AccessContext.build(user=user, enrollment=enrollment),
    )

    lessons = list(
        Lesson.objects.filter(unit=unit, status=ContentStatus.PUBLISHED)
        .annotate(
            ministerial_questions_count=Count(
                "questions",
                filter=Q(
                    questions__source_type=SourceType.MINISTERIAL,
                    questions__status=ContentStatus.PUBLISHED,
                ),
                distinct=True,
            ),
            has_summary=Exists(
                Summary.objects.filter(
                    lesson_id=OuterRef("pk"),
                    summary_type=SummaryType.LESSON,
                    status=ContentStatus.PUBLISHED,
                )
            ),
            has_smart_cards=Exists(
                FlashcardDeck.objects.filter(
                    lesson_id=OuterRef("pk"), status=ContentStatus.PUBLISHED
                )
            ),
            has_assessment=Exists(
                Assessment.objects.filter(
                    lesson_id=OuterRef("pk"),
                    assessment_type=AssessmentType.LESSON_TEST,
                    status=ContentStatus.PUBLISHED,
                )
            ),
        )
        .order_by("sort_order", "id")
    )
    lesson_ids = [str(lesson.id) for lesson in lessons]
    progress_by_lesson = {
        str(row.lesson_id): row
        for row in LessonProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            lesson_id__in=lesson_ids,
        )
    }
    active_progress = [
        row for row in progress_by_lesson.values() if row.completion_percentage > 0
    ]
    resume_progress = max(
        active_progress,
        key=lambda row: row.last_activity_at,
        default=None,
    )
    unit_progress = UnitProgress.objects.filter(
        user=user,
        study_enrollment=enrollment,
        unit=unit,
    ).first()

    completed_lessons = sum(
        1 for row in progress_by_lesson.values() if row.completion_percentage >= 100
    )
    completion_percentage = (
        float(unit_progress.completion_percentage) if unit_progress else 0.0
    )

    unit_assessment_ids = Assessment.objects.filter(
        Q(unit=unit) | Q(lesson__unit=unit),
        status=ContentStatus.PUBLISHED,
    ).values_list("id", flat=True)
    completed_attempts = AssessmentAttempt.objects.filter(
        user=user,
        study_enrollment=enrollment,
        assessment_id__in=unit_assessment_ids,
        status__in=_COMPLETED_ATTEMPT_STATUSES,
    )
    average_score = completed_attempts.aggregate(value=Avg("percentage"))["value"]

    base = {
        "unit": {
            "unit_id": str(unit.id),
            "subject_id": str(subject.id),
            "subject_name": subject.name_ar,
            "subject_icon_path": (
                subject.icon_path.url if subject.icon_path else None
            ),
            "title": unit.title,
            "description": unit.description,
            "sort_order": unit.sort_order,
            "number": list(
                Unit.objects.filter(
                    subject=subject,
                    status=ContentStatus.PUBLISHED,
                    sort_order__lte=unit.sort_order,
                ).values_list("id", flat=True)
            ).index(unit.id)
            + 1,
            "lessons_count": len(lessons),
            "is_free": access.source == "free_unit",
        },
        "access": access.to_dict(),
        "progress": {
            "completion_percentage": completion_percentage,
            "completed_lessons_count": completed_lessons,
            "lessons_count": len(lessons),
            "average_score": (
                float(average_score) if average_score is not None else None
            ),
            "last_activity": _iso(
                resume_progress.last_activity_at
                if resume_progress
                else unit_progress.last_activity_at if unit_progress else None
            ),
        },
        "resume_target": (
            {
                "lesson_id": str(resume_progress.lesson_id),
                "lesson_title": next(
                    lesson.title
                    for lesson in lessons
                    if str(lesson.id) == str(resume_progress.lesson_id)
                ),
            }
            if resume_progress
            else (
                {
                    "lesson_id": str(lessons[0].id),
                    "lesson_title": lessons[0].title,
                    "is_first_lesson": True,
                }
                if lessons
                else None
            )
        ),
    }

    # A direct link may expose safe unit metadata, but never protected lists.
    if not access.allowed:
        return {
            **base,
            "lessons": [],
            "tests": [],
            "summaries": [],
            "smart_card_decks": [],
        }, None

    lesson_items = []
    for lesson in lessons:
        row = progress_by_lesson.get(str(lesson.id))
        lesson_items.append(
            {
                "lesson_id": str(lesson.id),
                "unit_id": str(unit.id),
                "title": lesson.title,
                "description": lesson.description,
                "sort_order": lesson.sort_order,
                "progress_percentage": (
                    float(row.completion_percentage) if row else 0.0
                ),
                "completion_status": row.status if row else "not_started",
                "ministerial_questions_count": lesson.ministerial_questions_count,
                "has_summary": lesson.has_summary,
                "has_smart_cards": lesson.has_smart_cards,
                "has_assessment": lesson.has_assessment,
                "resume_target": (
                    {"lesson_id": str(lesson.id)}
                    if row and 0 < row.completion_percentage < 100
                    else None
                ),
            }
        )

    ministerial_models = list(
        MinisterialExamItem.objects.filter(
            question_version__question__unit=unit,
            question_version__question__source_type=SourceType.MINISTERIAL,
            question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam__status=ContentStatus.PUBLISHED,
        )
        .values(
            "ministerial_exam_id",
            "ministerial_exam__exam_year",
            "ministerial_exam__exam_role",
            "ministerial_exam__model_number",
        )
        .annotate(questions_count=Count("id"))
        .order_by(
            "-ministerial_exam__exam_year",
            "ministerial_exam__exam_role",
            "ministerial_exam__model_number",
            "ministerial_exam_id",
        )
    )
    ministerial_models.sort(
        key=lambda row: (
            -row["ministerial_exam__exam_year"],
            row["ministerial_exam__exam_role"] or "",
            _natural_model_key(row["ministerial_exam__model_number"]),
            str(row["ministerial_exam_id"]),
        )
    )
    unit_assessments = list(
        Assessment.objects.filter(
            unit=unit,
            lesson__isnull=True,
            assessment_type=AssessmentType.UNIT_TEST,
            status=ContentStatus.PUBLISHED,
        )
        .exclude(description=_DYNAMIC_UNIT_MINISTERIAL_MARKER)
        .annotate(
            actual_question_count=Count(
                "versions__items",
                filter=Q(
                    versions__is_current=True,
                    versions__items__question_version__question__status=ContentStatus.PUBLISHED,
                ),
                distinct=True,
            )
        )
        .order_by("created_at", "id")
    )
    tests = []
    if ministerial_models:
        maximum = max(
            1, getattr(settings, "ASSESSMENT_UNIT_MINISTERIAL_MAX_SIZE", 50)
        )
        groups = []
        for row in ministerial_models:
            part_sizes = balanced_part_sizes(row["questions_count"], maximum)
            role = row["ministerial_exam__exam_role"]
            role_label = {
                "first": "الدور الأول",
                "second": "الدور الثاني",
                "supplementary": "تكميلي",
                "other": "دور آخر",
            }.get(role)
            base_title = f"نموذج {row['ministerial_exam__model_number']}"
            if role_label:
                base_title += f" — {role_label}"
            base_title += " — أسئلة هذه الوحدة"
            for part_index, part_size in enumerate(part_sizes, 1):
                groups.append(
                    {
                        "source_kind": "unit_ministerial",
                        "source_id": str(unit.id),
                        "exam_id": str(row["ministerial_exam_id"]),
                        "title": (
                            f"{base_title} — الجزء {part_index}"
                            if len(part_sizes) > 1
                            else base_title
                        ),
                        "year": row["ministerial_exam__exam_year"],
                        "exam_role": role,
                        "model_number": row["ministerial_exam__model_number"],
                        "questions_count": part_size,
                        "model_questions_count": row["questions_count"],
                        "part_index": part_index,
                        "part_count": len(part_sizes),
                        "is_available": part_size > 0,
                    }
                )
        years = list(dict.fromkeys(group["year"] for group in groups))
        total_questions = sum(row["questions_count"] for row in ministerial_models)
        covered_questions = ministerial_coverage_count(
            user=user, enrollment=enrollment, unit_id=unit.id
        )
        tests.append(
            {
                "category": "ministerial",
                "label": "الوزاريات",
                "years": years,
                "groups": groups,
                "total_questions_count": total_questions,
                "covered_questions_count": covered_questions,
                "assessments": [],
            }
        )
    training_cards, training_total, training_covered, _ = training_batch_cards(
        user=user,
        enrollment=enrollment,
        scope_type=TrainingBatchScope.UNIT,
        source_id=unit.id,
    )
    static_unit_cards = [
        {
            "assessment_id": str(assessment.id),
            "source_kind": "assessment",
            "source_id": str(assessment.id),
            "title": assessment.title,
            "questions_count": assessment.actual_question_count,
            "is_available": assessment.actual_question_count > 0,
        }
        for assessment in unit_assessments
    ]
    if training_cards or static_unit_cards:
        tests.append(
            {
                "category": "training",
                "label": "اختبارات الوحدة",
                "years": [],
                "groups": [],
                "assessments": [*static_unit_cards, *training_cards],
                "total_questions_count": training_total,
                "covered_questions_count": training_covered,
            }
        )

    summaries = list(
        Summary.objects.filter(
            Q(
                summary_type=SummaryType.UNIT,
                unit=unit,
                lesson__isnull=True,
            )
            | Q(
                summary_type=SummaryType.LESSON,
                lesson__unit=unit,
                lesson__isnull=False,
            )
            | Q(
                summary_type=SummaryType.QUICK_REVIEW,
                unit=unit,
                lesson__isnull=True,
            )
            | Q(
                summary_type=SummaryType.QUICK_REVIEW,
                lesson__unit=unit,
                lesson__isnull=False,
            ),
            status=ContentStatus.PUBLISHED,
        )
        .select_related("lesson")
        .order_by("sort_order", "id")
        .distinct()
    )
    decks = list(
        FlashcardDeck.objects.filter(
            Q(unit=unit) | Q(lesson__unit=unit),
            status=ContentStatus.PUBLISHED,
        )
        .select_related("lesson")
        .annotate(cards_count=Count("cards", filter=Q(cards__is_active=True)))
        .order_by("sort_order", "id")
        .distinct()
    )
    resource_progress = {
        (row.resource_type, str(row.resource_id)): row
        for row in LearningResourceProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            unit=unit,
            resource_type__in=["summary", "flashcard_deck"],
        )
    }

    return {
        **base,
        "lessons": lesson_items,
        "tests": tests,
        "summaries": [
            {
                "id": str(item.id),
                "title": item.title,
                "description": item.body[:150] if item.body else "",
                "summary_type": item.summary_type,
                "lesson_id": str(item.lesson_id) if item.lesson_id else None,
                "lesson_title": item.lesson.title if item.lesson else None,
                "sort_order": item.sort_order,
                "progress_percentage": (
                    float(resource_progress[("summary", str(item.id))].completion_percentage)
                    if ("summary", str(item.id)) in resource_progress
                    else None
                ),
                "can_open": True,
            }
            for item in summaries
        ],
        "smart_card_decks": [
            {
                "id": str(item.id),
                "title": item.title,
                "description": item.description,
                "lesson_id": str(item.lesson_id) if item.lesson_id else None,
                "lesson_title": item.lesson.title if item.lesson else None,
                "cards_count": item.cards_count,
                "reviewed_count": (
                    int((resource_progress[("flashcard_deck", str(item.id))].resource_snapshot or {}).get("reviewed_count", 0))
                    if ("flashcard_deck", str(item.id)) in resource_progress
                    else 0
                ),
                "progress_percentage": (
                    float(resource_progress[("flashcard_deck", str(item.id))].completion_percentage)
                    if ("flashcard_deck", str(item.id)) in resource_progress
                    else None
                ),
                "review_status": (
                    resource_progress[("flashcard_deck", str(item.id))].status
                    if ("flashcard_deck", str(item.id)) in resource_progress
                    else "not_started"
                ),
                "can_open": True,
            }
            for item in decks
        ],
    }, None


def _natural_model_key(value):
    text = str(value or "")
    return (0, int(text)) if text.isdigit() else (1, text.casefold())
