import re

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery

from apps.assessments.models import Assessment, AssessmentType, AssessmentVersion
from apps.assessments.models import TrainingBatchScope
from apps.assessments.services.training import training_batch_cards
from apps.attempts.models import AssessmentAttempt, AttemptStatus
from apps.content.models import (
    FlashcardDeck,
    LessonExplanation,
    Summary,
    SummaryType,
)
from apps.curriculum.models import ContentStatus, Lesson, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import AccessContext, check_resource_access
from apps.ministerial_exams.models import LessonMinisterialBatch, MinisterialExam
from apps.ministerial_exams.services import (
    ministerial_coverage_count,
    sync_lesson_ministerial_batches,
)
from apps.progress.models import LearningResourceProgress, LessonProgress


_COMPLETED_ATTEMPT_STATUSES = {
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
}
_TRAINING_TYPES = {
    AssessmentType.LESSON_TEST,
    AssessmentType.TRAINING_TEST,
    AssessmentType.SELF_PRACTICE,
}
_TEST_CATEGORY_BY_TYPE = {
    **{assessment_type: "training" for assessment_type in _TRAINING_TYPES},
    AssessmentType.CUSTOM_TEST: "custom",
}
_CATEGORY_LABELS = {
    "training": "تدريبية",
    "custom": "مخصصة",
}


def _iso(value):
    return value.isoformat() if value else None


def _has_inline_images(body: str) -> bool:
    return bool(re.search(r"!\[[^\]]*\]\([^)]*\)|<img\b", body or "", re.I))


def get_lesson_center(*, user, subject_id: str, unit_id: str, lesson_id: str):
    """Build a lightweight, read-only lesson-center model."""
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

    lesson = Lesson.objects.filter(id=lesson_id, unit=unit).first()
    if lesson is None or (
        lesson.status != ContentStatus.PUBLISHED and not user.is_staff
    ):
        return None, "lesson"

    access = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type="unit",
        resource_id=str(unit.id),
        context=AccessContext.build(user=user, enrollment=enrollment),
    )
    published_lesson_ids = list(
        Lesson.objects.filter(unit=unit, status=ContentStatus.PUBLISHED)
        .order_by("sort_order", "id")
        .values_list("id", flat=True)
    )
    lesson_number = (
        published_lesson_ids.index(lesson.id) + 1
        if lesson.id in published_lesson_ids
        else 1
    )
    lesson_progress = LessonProgress.objects.filter(
        user=user,
        study_enrollment=enrollment,
        lesson=lesson,
    ).first()
    completion_percentage = (
        float(lesson_progress.completion_percentage) if lesson_progress else 0.0
    )
    completion_status = lesson_progress.status if lesson_progress else "not_started"
    access_payload = access.to_dict()
    access_payload["is_free"] = access.source == "free_unit"

    base = {
        "lesson": {
            "lesson_id": str(lesson.id),
            "unit_id": str(unit.id),
            "subject_id": str(subject.id),
            "title": lesson.title,
            "description": lesson.description,
            "sort_order": lesson.sort_order,
            "lesson_number": lesson_number,
            "status": lesson.status,
            "subject_name": subject.name_ar,
            "unit_name": unit.title,
            "subject_icon_path": subject.icon_path.url if subject.icon_path else None,
        },
        "access": access_payload,
        "progress": {
            "completion_percentage": completion_percentage,
            "completion_status": completion_status,
            "started_at": _iso(lesson_progress.created_at if lesson_progress else None),
            "completed_at": _iso(lesson_progress.completed_at if lesson_progress else None),
            "last_activity_at": _iso(
                lesson_progress.last_activity_at if lesson_progress else None
            ),
        },
        "resume_target": None,
        "content": None,
    }

    if not access.allowed:
        return {
            **base,
            "summaries": [],
            "smart_card_decks": [],
            "tests": [],
        }, None

    explanation = LessonExplanation.objects.filter(
        lesson=lesson,
        status=ContentStatus.PUBLISHED,
    ).first()
    summaries = list(
        Summary.objects.filter(
            lesson=lesson,
            status=ContentStatus.PUBLISHED,
            summary_type__in=[SummaryType.LESSON, SummaryType.QUICK_REVIEW],
        )
        .order_by("sort_order", "id")
    )
    decks = list(
        FlashcardDeck.objects.filter(
            lesson=lesson,
            status=ContentStatus.PUBLISHED,
        )
        .annotate(cards_count=Count("cards", filter=Q(cards__is_active=True)))
        .order_by("sort_order", "id")
    )

    current_version = AssessmentVersion.objects.filter(
        assessment_id=OuterRef("pk"), is_current=True
    )
    assessments = list(
        Assessment.objects.filter(
            lesson=lesson,
            assessment_type__in=_TEST_CATEGORY_BY_TYPE.keys(),
            status=ContentStatus.PUBLISHED,
        )
        .exclude(description__startswith="dynamic-source:")
        .annotate(
            current_question_count=Count(
                "versions__items",
                filter=Q(
                    versions__is_current=True,
                    versions__items__question_version__question__status=ContentStatus.PUBLISHED,
                ),
                distinct=True,
            ),
            current_duration=Subquery(
                current_version.values("duration_minutes")[:1],
                output_field=IntegerField(),
            ),
        )
        .order_by("created_at", "id")
    )
    assessment_ids = [item.id for item in assessments]
    attempts = list(
        AssessmentAttempt.objects.filter(
            user=user,
            study_enrollment=enrollment,
            assessment_id__in=assessment_ids,
        ).order_by("assessment_id", "-created_at")
    )
    attempts_by_assessment = {}
    for attempt in attempts:
        attempts_by_assessment.setdefault(str(attempt.assessment_id), []).append(attempt)

    resource_ids = [
        *([str(explanation.id)] if explanation else []),
        *(str(item.id) for item in summaries),
        *(str(item.id) for item in decks),
        *(str(item.id) for item in assessments),
    ]
    progress_rows = list(
        LearningResourceProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            resource_id__in=resource_ids,
            resource_type__in=[
                "lesson_explanation",
                "summary",
                "flashcard_deck",
                "assessment",
            ],
        )
    )
    progress_by_resource = {
        (row.resource_type, str(row.resource_id)): row for row in progress_rows
    }

    exam_groups = list(
        MinisterialExam.objects.filter(
            subject=subject,
            status=ContentStatus.PUBLISHED,
            items__question_version__question__lesson=lesson,
            items__question_version__question__status=ContentStatus.PUBLISHED,
        )
        .annotate(
            lesson_questions_count=Count(
                "items",
                filter=Q(
                    items__question_version__question__lesson=lesson,
                    items__question_version__question__status=ContentStatus.PUBLISHED,
                ),
                distinct=True,
            )
        )
        .order_by("-exam_year", "model_number", "id")
        .distinct()
    )

    tests = []
    if exam_groups:
        sync_lesson_ministerial_batches(lesson)
        stable_batches = list(
            LessonMinisterialBatch.objects.filter(lesson=lesson)
            .annotate(
                questions_count=Count(
                    "batch_items",
                    filter=Q(
                        batch_items__ministerial_exam_item__question_version__question__status=ContentStatus.PUBLISHED,
                        batch_items__ministerial_exam_item__ministerial_exam__status=ContentStatus.PUBLISHED,
                    ),
                )
            )
            .order_by("batch_index")
        )
        aggregate = Assessment.objects.filter(
            lesson=lesson,
            assessment_type=AssessmentType.LESSON_MINISTERIAL,
            status=ContentStatus.PUBLISHED,
        ).first()
        aggregate_attempts = (
            list(
                AssessmentAttempt.objects.filter(
                    user=user,
                    study_enrollment=enrollment,
                    assessment=aggregate,
                ).order_by("-created_at")
            )
            if aggregate
            else []
        )
        total_questions = sum(
            exam.lesson_questions_count for exam in exam_groups
        )
        covered_questions = ministerial_coverage_count(
            user=user, enrollment=enrollment, lesson_id=lesson.id
        )
        batch_tests = []
        for stable_batch in stable_batches:
            batch_index = stable_batch.batch_index
            batch_size = stable_batch.questions_count
            batch_scope = {
                "kind": "lesson_ministerial",
                "source_id": str(lesson.id),
                "batch": batch_index,
            }
            batch_attempts = [
                item for item in aggregate_attempts
                if item.source_scope == batch_scope
            ]
            latest = batch_attempts[0] if batch_attempts else None
            unfinished = next(
                (
                    item for item in batch_attempts
                    if item.status not in _COMPLETED_ATTEMPT_STATUSES
                ),
                None,
            )
            scores = [float(item.percentage) for item in batch_attempts]
            batch_tests.append(
                {
                    "assessment_id": str(aggregate.id) if aggregate else None,
                    "source_kind": "lesson_ministerial",
                    "source_id": str(lesson.id),
                    "assessment_type": AssessmentType.LESSON_MINISTERIAL,
                    "title": f"الاختبار الوزاري {batch_index}",
                    "questions_count": batch_size,
                    "total_pool_question_count": total_questions,
                    "covered_questions_count": covered_questions,
                    "session_question_count": batch_size,
                    "batch_index": batch_index,
                    "batch_count": len(stable_batches),
                    "duration": None,
                    "attempt_status": latest.status if latest else "not_started",
                    "unfinished_attempt_id": str(unfinished.id) if unfinished else None,
                    "last_score": float(latest.percentage) if latest else None,
                    "best_score": max(scores) if scores else None,
                    "is_available": True,
                }
            )
        tests.append(
            {
                "category": "ministerial",
                "label": "وزاريات الدرس",
                "tests": batch_tests,
            }
        )

    training_cards, _, _, _ = training_batch_cards(
        user=user,
        enrollment=enrollment,
        scope_type=TrainingBatchScope.LESSON,
        source_id=lesson.id,
    )
    if training_cards:
        tests.append(
            {
                "category": "training",
                "label": "تدريبات الدرس",
                "tests": training_cards,
            }
        )

    for category in ("training", "custom"):
        category_assessments = [
            item
            for item in assessments
            if _TEST_CATEGORY_BY_TYPE[item.assessment_type] == category
        ]
        if not category_assessments:
            continue
        static_cards = [
            _assessment_metadata(
                assessment=item,
                attempts=attempts_by_assessment.get(str(item.id), []),
            )
            for item in category_assessments
        ]
        existing_section = next(
            (section for section in tests if section["category"] == category), None
        )
        if existing_section is not None:
            existing_section["tests"].extend(static_cards)
        else:
            tests.append(
                {
                    "category": category,
                    "label": _CATEGORY_LABELS[category],
                    "tests": static_cards,
                }
            )

    resume_candidates = []
    section_by_resource = {
        "lesson_explanation": "content",
        "summary": "summaries",
        "flashcard_deck": "smart_cards",
        "assessment": "tests",
    }
    type_by_resource = {
        "lesson_explanation": "content",
        "summary": "summary",
        "flashcard_deck": "smart_card_deck",
        "assessment": "assessment",
    }
    for row in progress_rows:
        if row.last_activity_at:
            resume_candidates.append(
                (
                    row.last_activity_at,
                    {
                        "type": type_by_resource[row.resource_type],
                        "resource_id": str(row.resource_id),
                        "section": section_by_resource[row.resource_type],
                        "progress": float(row.completion_percentage),
                    },
                )
            )
    for attempt in attempts:
        if (
            attempt.status not in _COMPLETED_ATTEMPT_STATUSES
            and attempt.last_activity_at
        ):
            resume_candidates.append(
                (
                    attempt.last_activity_at,
                    {
                        "type": "assessment",
                        "resource_id": str(attempt.assessment_id),
                        "section": "tests",
                        "progress": None,
                    },
                )
            )
    if resume_candidates:
        base["resume_target"] = max(resume_candidates, key=lambda item: item[0])[1]

    if explanation:
        content_progress = progress_by_resource.get(
            ("lesson_explanation", str(explanation.id))
        )
        base["content"] = {
            "content_id": str(explanation.id),
            "title": explanation.title or lesson.title,
            "description": "",
            "content_type": explanation.content_format,
            "sort_order": 0,
            "estimated_duration": None,
            "has_images": _has_inline_images(explanation.body),
            "has_attachments": False,
            "progress": (
                float(content_progress.completion_percentage)
                if content_progress
                else 0.0
            ),
            "status": explanation.status,
            "is_available": True,
        }

    return {
        **base,
        "summaries": [
            {
                "id": str(item.id),
                "title": item.title,
                "description": "",
                "summary_type": item.summary_type,
                "lesson_id": str(item.lesson_id),
                "lesson_title": lesson.title,
                "sort_order": item.sort_order,
                "progress_percentage": _progress_percentage(
                    progress_by_resource, "summary", item.id
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
                "lesson_id": str(item.lesson_id),
                "lesson_title": lesson.title,
                "sort_order": item.sort_order,
                "cards_count": item.cards_count,
                "reviewed_count": _reviewed_count(
                    progress_by_resource, "flashcard_deck", item.id
                ),
                "due_count": 0,
                "progress_percentage": _progress_percentage(
                    progress_by_resource, "flashcard_deck", item.id
                ),
                "review_status": _progress_status(
                    progress_by_resource, "flashcard_deck", item.id
                ),
                "is_available": True,
            }
            for item in decks
        ],
        "tests": tests,
    }, None


def _progress_percentage(progress_by_resource, resource_type, resource_id):
    row = progress_by_resource.get((resource_type, str(resource_id)))
    return float(row.completion_percentage) if row else None


def _progress_status(progress_by_resource, resource_type, resource_id):
    row = progress_by_resource.get((resource_type, str(resource_id)))
    return row.status if row else "not_started"


def _reviewed_count(progress_by_resource, resource_type, resource_id):
    row = progress_by_resource.get((resource_type, str(resource_id)))
    return int((row.resource_snapshot or {}).get("reviewed_count", 0)) if row else 0


def _assessment_metadata(*, assessment, attempts):
    latest = attempts[0] if attempts else None
    unfinished = next(
        (item for item in attempts if item.status not in _COMPLETED_ATTEMPT_STATUSES),
        None,
    )
    scores = [float(item.percentage) for item in attempts if item.percentage is not None]
    return {
        "assessment_id": str(assessment.id),
        "assessment_type": assessment.assessment_type,
        "title": assessment.title,
        "questions_count": assessment.current_question_count or 0,
        "duration": assessment.current_duration,
        "attempt_status": latest.status if latest else "not_started",
        "unfinished_attempt_id": str(unfinished.id) if unfinished else None,
        "last_score": (
            float(latest.percentage)
            if latest is not None and latest.percentage is not None
            else None
        ),
        "best_score": max(scores) if scores else None,
        "is_available": (assessment.current_question_count or 0) > 0,
    }
