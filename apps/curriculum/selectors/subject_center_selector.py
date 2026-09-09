from collections import defaultdict

from django.db.models import Avg, Count, Prefetch, Q

from apps.assessments.models import AssessmentType, AssessmentVersion, TrainingBatchScope
from apps.assessments.services.training import training_batch_cards
from apps.attempts.models import AssessmentAttempt, AttemptStatus
from apps.content.models import Summary, SummaryType
from apps.curriculum.models import ContentStatus, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import (
    AccessContext,
    check_resource_access,
    check_resources_access_batch,
)
from apps.ministerial_exams.models import MinisterialExam
from apps.progress.models import LessonProgress, SubjectProgress, UnitProgress


_INCOMPLETE_ATTEMPT_STATUSES = {
    AttemptStatus.CREATED,
    AttemptStatus.IN_PROGRESS,
    AttemptStatus.PAUSED,
}


def _access_status(decision) -> str:
    if not decision or not decision.allowed:
        return "locked"
    if decision.source == "free_unit":
        return "free"
    if decision.source in {"subscription", "user_entitlement"}:
        return "subscribed"
    return "available"


def _attempt_payload(attempt):
    if attempt is None:
        return None
    return {
        "id": str(attempt.id),
        "status": attempt.status,
        "score": float(attempt.score),
        "maximum_score": float(attempt.maximum_score),
        "percentage": float(attempt.percentage),
    }


def get_subject_center(*, user, subject_id: str):
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

    units = list(
        Unit.objects.filter(subject=subject, status=ContentStatus.PUBLISHED)
        .annotate(
            published_lessons_count=Count(
                "lessons",
                filter=Q(lessons__status=ContentStatus.PUBLISHED),
                distinct=True,
            ),
            unit_tests_count=Count(
                "assessments",
                filter=Q(
                    assessments__status=ContentStatus.PUBLISHED,
                    assessments__assessment_type=AssessmentType.UNIT_TEST,
                ),
                distinct=True,
            ),
            summaries_count=Count(
                "summaries",
                filter=Q(summaries__status=ContentStatus.PUBLISHED),
                distinct=True,
            ),
            smart_cards_count=Count(
                "flashcard_decks",
                filter=Q(flashcard_decks__status=ContentStatus.PUBLISHED),
                distinct=True,
            ),
        )
        .order_by("sort_order", "id")
    )
    unit_ids = [str(unit.id) for unit in units]
    context = AccessContext.build(user=user, enrollment=enrollment)
    subject_training_access = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type="subject",
        resource_id=str(subject.id),
        context=context,
    )
    access_map = check_resources_access_batch(
        user=user,
        enrollment=enrollment,
        resources=[{"type": "unit", "id": unit_id} for unit_id in unit_ids],
        context=context,
    )
    unit_progress = {
        str(row.unit_id): row
        for row in UnitProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            unit_id__in=unit_ids,
        )
    }

    unit_items = []
    for index, unit in enumerate(units, start=1):
        unit_id = str(unit.id)
        progress = unit_progress.get(unit_id)
        decision = access_map.get(("unit", unit_id))
        unit_items.append(
            {
                "id": unit_id,
                "number": index,
                "title": unit.title,
                "description": unit.description,
                "sort_order": unit.sort_order,
                "published_lessons_count": unit.published_lessons_count,
                "unit_tests_count": unit.unit_tests_count,
                "summaries_count": unit.summaries_count,
                "smart_cards_count": unit.smart_cards_count,
                "access_status": _access_status(decision),
                "access": decision.to_dict() if decision else None,
                "progress": (
                    {
                        "status": progress.status,
                        "completion_percentage": float(progress.completion_percentage),
                        "lessons_completed": progress.lessons_completed,
                        "lessons_total": progress.lessons_total,
                    }
                    if progress
                    else None
                ),
            }
        )

    summaries = list(
        Summary.objects.filter(
            subject=subject,
            summary_type=SummaryType.SUBJECT,
            unit__isnull=True,
            lesson__isnull=True,
            status=ContentStatus.PUBLISHED,
        )
        .select_related("unit", "lesson")
        .order_by("sort_order", "-created_at")
    )
    summary_items = [
        {
            "id": str(summary.id),
            "title": summary.title,
            "summary_type": summary.summary_type,
            "unit_id": str(summary.unit_id) if summary.unit_id else None,
            "unit_title": summary.unit.title if summary.unit else None,
            "lesson_id": str(summary.lesson_id) if summary.lesson_id else None,
            "lesson_title": summary.lesson.title if summary.lesson else None,
        }
        for summary in summaries
    ]

    current_version_qs = AssessmentVersion.objects.filter(is_current=True).order_by(
        "-version_number"
    )
    exams = list(
        MinisterialExam.objects.filter(subject=subject, status=ContentStatus.PUBLISHED)
        .select_related("assessment")
        .prefetch_related(
            Prefetch(
                "assessment__versions",
                queryset=current_version_qs,
                to_attr="current_versions",
            )
        )
        .order_by("-exam_year", "model_number", "id")
    )
    exam_access_map = check_resources_access_batch(
        user=user,
        enrollment=enrollment,
        resources=[
            {"type": "ministerial_exam", "id": str(exam.id)}
            for exam in exams
        ],
        context=context,
    )
    assessment_ids = [str(exam.assessment_id) for exam in exams if exam.assessment_id]
    attempts = list(
        AssessmentAttempt.objects.filter(
            user=user,
            study_enrollment=enrollment,
            assessment_id__in=assessment_ids,
        ).order_by("-created_at")
    )
    attempts_by_assessment = defaultdict(list)
    for attempt in attempts:
        attempts_by_assessment[str(attempt.assessment_id)].append(attempt)

    exam_items = []
    for exam in exams:
        exam_decision = exam_access_map.get(("ministerial_exam", str(exam.id)))
        assessment_id = str(exam.assessment_id) if exam.assessment_id else None
        exam_attempts = attempts_by_assessment.get(assessment_id, [])
        latest_attempt = exam_attempts[0] if exam_attempts else None
        incomplete_attempt = next(
            (
                attempt
                for attempt in exam_attempts
                if attempt.status in _INCOMPLETE_ATTEMPT_STATUSES
            ),
            None,
        )
        completed_attempts = [
            attempt
            for attempt in exam_attempts
            if attempt.status
            in {
                AttemptStatus.SUBMITTED,
                AttemptStatus.EVALUATED,
                AttemptStatus.PENDING_REVIEW,
            }
        ]
        best_attempt = max(completed_attempts, key=lambda item: item.percentage, default=None)
        versions = getattr(exam.assessment, "current_versions", []) if exam.assessment else []
        version = versions[0] if versions else None
        exam_items.append(
            {
                "id": str(exam.id),
                "assessment_id": assessment_id,
                "title": exam.title,
                "model_number": exam.model_number,
                "year": exam.exam_year,
                "exam_role": exam.exam_role,
                "total_questions": exam.total_questions,
                "total_points": float(exam.total_points) if exam.total_points is not None else None,
                "duration_minutes": (
                    exam.duration_minutes
                    if exam.duration_minutes is not None
                    else version.duration_minutes if version else None
                ),
                "can_start": bool(
                    assessment_id is not None
                    and exam_decision
                    and exam_decision.allowed
                ),
                "free_access_rank": exam.free_access_rank,
                "access": exam_decision.to_dict() if exam_decision else None,
                "incomplete_attempt": _attempt_payload(incomplete_attempt),
                "latest_attempt": _attempt_payload(latest_attempt),
                "best_attempt": _attempt_payload(best_attempt),
            }
        )

    subject_progress = SubjectProgress.objects.filter(
        user=user,
        study_enrollment=enrollment,
        subject=subject,
    ).first()
    lesson_progress = list(
        LessonProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            lesson__unit__subject=subject,
        )
        .select_related("lesson")
        .order_by("-completion_percentage", "-last_activity_at")[:5]
    )
    completed_unit_count = sum(
        1 for progress in unit_progress.values() if progress.completion_percentage >= 100
    )
    completed_lesson_count = LessonProgress.objects.filter(
        user=user,
        study_enrollment=enrollment,
        lesson__unit__subject=subject,
        completion_percentage__gte=100,
    ).count()
    total_lesson_count = sum(unit.published_lessons_count for unit in units)
    attempted_exam_count = len(
        {
            str(attempt.assessment_id)
            for attempt in attempts
            if attempt.status
            in {
                AttemptStatus.SUBMITTED,
                AttemptStatus.EVALUATED,
                AttemptStatus.PENDING_REVIEW,
            }
        }
    )
    average_score = (
        AssessmentAttempt.objects.filter(
            user=user,
            study_enrollment=enrollment,
            assessment_id__in=assessment_ids,
            status__in=[AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED],
        ).aggregate(value=Avg("percentage"))["value"]
        if assessment_ids
        else None
    )
    stats_available = bool(subject_progress or attempts or unit_progress or lesson_progress)
    statistics = {
        "has_activity": stats_available,
        "overall_completion_percentage": (
            float(subject_progress.completion_percentage) if subject_progress else None
        ),
        "units_completed": completed_unit_count,
        "units_total": len(units),
        "lessons_completed": completed_lesson_count,
        "lessons_total": total_lesson_count,
        "attempted_exams_count": attempted_exam_count,
        "average_score": float(average_score) if average_score is not None else None,
        "unit_progress": [
            {
                "unit_id": item["id"],
                "unit_title": item["title"],
                "completion_percentage": (
                    item["progress"]["completion_percentage"] if item["progress"] else 0.0
                ),
            }
            for item in unit_items
        ],
        "top_lessons": [
            {
                "lesson_id": str(progress.lesson_id),
                "lesson_title": progress.lesson.title,
                "completion_percentage": float(progress.completion_percentage),
            }
            for progress in lesson_progress
            if progress.completion_percentage > 0
        ],
        "best_exams": [
            {
                "exam_id": item["id"],
                "exam_title": item["title"],
                "percentage": item["best_attempt"]["percentage"],
            }
            for item in sorted(
                (item for item in exam_items if item["best_attempt"]),
                key=lambda item: item["best_attempt"]["percentage"],
                reverse=True,
            )[:5]
        ],
    }

    training_cards, training_total, training_covered, training_batch_count = training_batch_cards(
        user=user,
        enrollment=enrollment,
        scope_type=TrainingBatchScope.SUBJECT,
        source_id=subject.id,
        limit=6,
    )
    # Subject training has its own free-access allowance.  Gating this section by
    # the parent subject decision would hide that allowance before the per-batch
    # access service had a chance to apply it.
    training_access = next(
        (card["access"] for card in training_cards if card["access"]["allowed"]),
        training_cards[0]["access"] if training_cards else subject_training_access.to_dict(),
    )
    training = {
        "access": training_access,
        "tests": training_cards,
        "total_questions_count": training_total,
        "covered_questions_count": training_covered,
        "batch_count": training_batch_count,
        "has_more": training_batch_count > len(training_cards),
    }

    return (
        {
            "subject": {
                "id": str(subject.id),
                "name": subject.name_ar,
                "description": subject.description,
                "icon_path": subject.icon_path.url if subject.icon_path else None,
                "cover_image_path": subject.cover_image_path.url if subject.cover_image_path else None,
                "grade_name": enrollment.grade.name_ar,
                "section_name": enrollment.section.name_ar if enrollment.section else None,
            },
            "units": unit_items,
            "exam_years": sorted({exam.exam_year for exam in exams}, reverse=True),
            "ministerial_exams": exam_items,
            "summaries": summary_items,
            "training": training,
            "statistics": statistics,
        },
        None,
    )
