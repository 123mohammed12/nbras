from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, F, Q, Sum

from apps.analytics.models import QuestionQualityContribution
from apps.assessments.models import TrainingBatchScope
from apps.assessments.services.training import (
    eligible_training_question_count,
    training_coverage_count,
)
from apps.attempts.models import AttemptQuestion, AttemptStatus, AttemptType
from apps.curriculum.models import ContentStatus, Subject
from apps.ministerial_exams.models import MinisterialExamItem
from apps.ministerial_exams.services import ministerial_coverage_count
from apps.progress.services.mastery import (
    mastery_weakness_signals,
    top_actionable_weaknesses,
)
from apps.question_bank.models import DifficultyLevel, QuestionType, QuestionVersion, SourceType


FINAL_COVERAGE_STATUSES = (
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
)
REMEDIATION_KINDS = ("wrong_answers_test", "weakness_practice")


def _scoped_contributions(
    *, user, enrollment, subject_id=None, unit_id=None, lesson_id=None
):
    query = QuestionQualityContribution.objects.filter(
        user=user, study_enrollment=enrollment
    )
    if lesson_id is not None:
        query = query.filter(lesson_id=lesson_id)
    elif unit_id is not None:
        query = query.filter(unit_id=unit_id)
    elif subject_id is not None:
        query = query.filter(subject_id=subject_id)
    return query


def _summary(query) -> dict:
    totals = query.aggregate(
        presented_count=Count("id"),
        answered_count=Count("id", filter=Q(was_answered=True)),
        graded_count=Count(
            "id", filter=Q(outcome__in=("correct", "incorrect", "partial"))
        ),
        pending_count=Count("id", filter=Q(outcome="pending")),
        earned_points=Sum("awarded_points"),
        maximum_gradable_points=Sum("maximum_gradable_points"),
        attempts_count=Count("attempt_question__attempt_id", distinct=True),
    )
    earned = totals["earned_points"] or Decimal("0")
    maximum = totals["maximum_gradable_points"] or Decimal("0")
    if maximum <= 0:
        return {
            "state": "unknown",
            "has_evidence": False,
            "performance_ratio": None,
            "percentage": None,
            "earned_points": None,
            "maximum_gradable_points": None,
            **{key: value for key, value in totals.items() if key not in ("earned_points", "maximum_gradable_points")},
        }
    ratio = earned / maximum
    return {
        "state": "known",
        "has_evidence": True,
        "performance_ratio": round(float(ratio), 4),
        "percentage": round(float(ratio * 100), 2),
        "earned_points": float(earned),
        "maximum_gradable_points": float(maximum),
        **{key: value for key, value in totals.items() if key not in ("earned_points", "maximum_gradable_points")},
    }


def _breakdown(query, field: str, expected=()) -> dict:
    rows = {
        str(row[field]): row
        for row in query.values(field).annotate(
            presented_count=Count("id"),
            answered_count=Count("id", filter=Q(was_answered=True)),
            graded_count=Count(
                "id", filter=Q(outcome__in=("correct", "incorrect", "partial"))
            ),
            pending_count=Count("id", filter=Q(outcome="pending")),
            earned_points=Sum("awarded_points"),
            maximum_gradable_points=Sum("maximum_gradable_points"),
            attempts_count=Count("attempt_question__attempt_id", distinct=True),
        )
    }
    result = {}
    for key in dict.fromkeys([*(str(value) for value in expected), *rows.keys()]):
        row = rows.get(key)
        if row is None or not row["maximum_gradable_points"]:
            result[key] = {
                "state": "unknown",
                "has_evidence": False,
                "performance_ratio": None,
                "percentage": None,
                "earned_points": None,
                "maximum_gradable_points": None,
                "presented_count": row["presented_count"] if row else 0,
                "answered_count": row["answered_count"] if row else 0,
                "graded_count": row["graded_count"] if row else 0,
                "pending_count": row["pending_count"] if row else 0,
                "attempts_count": row["attempts_count"] if row else 0,
            }
            continue
        maximum = Decimal(row["maximum_gradable_points"])
        earned = Decimal(row["earned_points"] or 0)
        result[key] = {
            "state": "known",
            "has_evidence": True,
            "performance_ratio": round(float(earned / maximum), 4),
            "percentage": round(float(earned / maximum * 100), 2),
            "earned_points": float(earned),
            "maximum_gradable_points": float(maximum),
            "presented_count": row["presented_count"],
            "answered_count": row["answered_count"],
            "graded_count": row["graded_count"],
            "pending_count": row["pending_count"],
            "attempts_count": row["attempts_count"],
        }
    return result


def _time_summary(query) -> dict:
    reliable = query.filter(response_time_seconds__isnull=False).aggregate(
        total=Sum("response_time_seconds"), count=Count("id")
    )
    count = reliable["count"] or 0
    total = reliable["total"] or 0
    return {
        "state": "known" if count else "unavailable",
        "response_time_sample_count": count,
        "average_time_per_answered_question_seconds": (
            round(total / count, 2) if count else None
        ),
        "limitation": None if count else "per_question_timing_not_reliably_captured",
    }


def _coverage_attempt_questions(*, user, enrollment):
    return (
        AttemptQuestion.objects.filter(
            attempt__user=user,
            attempt__study_enrollment=enrollment,
            attempt__status__in=FINAL_COVERAGE_STATUSES,
            attempt__submitted_at__isnull=False,
            attempt__attempt_type__in=(AttemptType.NORMAL, AttemptType.RETRY_FULL),
        )
        .exclude(attempt__dynamic_assessment_type__in=REMEDIATION_KINDS)
    )


def _coverage_item(covered: int, eligible: int) -> dict:
    return {
        "state": "known" if eligible else "unknown",
        "covered": covered,
        "eligible": eligible,
        "percent": round(covered * 100 / eligible, 2) if eligible else None,
    }


def coverage_summary(
    *, user, enrollment, subject_id=None, unit_id=None, lesson_id=None
) -> dict:
    if lesson_id is not None:
        scope_type, scope_id = TrainingBatchScope.LESSON, lesson_id
        ministerial_covered = ministerial_coverage_count(
            user=user, enrollment=enrollment, lesson_id=lesson_id
        )
    elif unit_id is not None:
        scope_type, scope_id = TrainingBatchScope.UNIT, unit_id
        ministerial_covered = ministerial_coverage_count(
            user=user, enrollment=enrollment, unit_id=unit_id
        )
    elif subject_id is not None:
        scope_type, scope_id = TrainingBatchScope.SUBJECT, subject_id
        ministerial_covered = ministerial_coverage_count(
            user=user, enrollment=enrollment, subject_id=subject_id
        )
    else:
        scope_type = scope_id = None
        ministerial_covered = (
            _coverage_attempt_questions(user=user, enrollment=enrollment)
            .filter(source_type=SourceType.MINISTERIAL)
            .exclude(ministerial_exam_item_id__isnull=True)
            .values("ministerial_exam_item_id")
            .distinct()
            .count()
        )

    eligible_ministerial = MinisterialExamItem.objects.filter(
        ministerial_exam__status=ContentStatus.PUBLISHED,
        question_version__question__status=ContentStatus.PUBLISHED,
        question_version__status=ContentStatus.PUBLISHED,
        question_version__question__current_version_id=F("question_version_id"),
        question_version__question__subject__grade_id=enrollment.grade_id,
        question_version__question__subject__section_id=enrollment.section_id,
    )
    if lesson_id is not None:
        eligible_ministerial = eligible_ministerial.filter(
            question_version__question__lesson_id=lesson_id
        )
    elif unit_id is not None:
        eligible_ministerial = eligible_ministerial.filter(
            question_version__question__unit_id=unit_id
        )
    elif subject_id is not None:
        eligible_ministerial = eligible_ministerial.filter(
            question_version__question__subject_id=subject_id
        )
    ministerial_eligible = eligible_ministerial.count()

    if scope_type is not None:
        training_eligible = eligible_training_question_count(
            scope_type=scope_type, source_id=scope_id
        )
        training_covered = training_coverage_count(
            user=user,
            enrollment=enrollment,
            scope_type=scope_type,
            source_id=scope_id,
        )
    else:
        subject_ids = Subject.objects.filter(
            grade_id=enrollment.grade_id,
            section_id=enrollment.section_id,
            status=ContentStatus.PUBLISHED,
        ).values("id")
        training_eligible = QuestionVersion.objects.filter(
            question__subject_id__in=subject_ids,
            question__source_type=SourceType.TRAINING,
            question__status=ContentStatus.PUBLISHED,
            status=ContentStatus.PUBLISHED,
            question__current_version_id=F("id"),
        ).count()
        training_covered = (
            _coverage_attempt_questions(user=user, enrollment=enrollment)
            .filter(source_type=SourceType.TRAINING)
            .values("question_version__question_id")
            .distinct()
            .count()
        )
    return {
        "ministerial": _coverage_item(ministerial_covered, ministerial_eligible),
        "training": _coverage_item(training_covered, training_eligible),
    }


def _practice_action(signal: dict) -> dict:
    return {
        "type": "weakness_practice",
        "subject_id": signal["scope"]["subject_id"],
        "unit_id": signal["scope"].get("unit_id"),
        "lesson_id": signal["scope"].get("lesson_id"),
        "dimension": signal["dimension"],
        "value": signal["value"],
    }


def _weaknesses(*, user, enrollment, subject=None, unit=None, lesson=None):
    if subject is None:
        signals = top_actionable_weaknesses(
            user=user, enrollment=enrollment, limit=5
        )
    else:
        signals = mastery_weakness_signals(
            user=user,
            enrollment=enrollment,
            subject=subject,
            unit=unit,
            lesson=lesson,
        )["signals"]
    signals.sort(
        key=lambda row: (
            row["mastery_score"],
            -row["effective_evidence"],
            row["dimension"],
            row["value"],
        )
    )
    return [{**row, "practice_action": _practice_action(row)} for row in signals[:5]]


def student_analytics(
    *, user, enrollment, mastery, subject=None, unit=None, lesson=None
) -> dict:
    query = _scoped_contributions(
        user=user,
        enrollment=enrollment,
        subject_id=subject.id if subject else None,
        unit_id=unit.id if unit else None,
        lesson_id=lesson.id if lesson else None,
    )
    core = query.filter(is_remediation=False)
    remediation = query.filter(is_remediation=True)
    return {
        "performance": {
            "policy": "all_finalized_core_attempt_question_points",
            "core": _summary(core),
            "remediation": _summary(remediation),
        },
        "coverage": coverage_summary(
            user=user,
            enrollment=enrollment,
            subject_id=subject.id if subject else None,
            unit_id=unit.id if unit else None,
            lesson_id=lesson.id if lesson else None,
        ),
        "trend": {
            "state": mastery.get("trend", "insufficient_data"),
            "source": "ar08_mastery",
        },
        "weaknesses": _weaknesses(
            user=user,
            enrollment=enrollment,
            subject=subject,
            unit=unit,
            lesson=lesson,
        ),
        "source_breakdown": _breakdown(
            core, "source_type", (SourceType.MINISTERIAL, SourceType.TRAINING)
        ),
        "assessment_kind_breakdown": _breakdown(core, "assessment_kind"),
        "difficulty_breakdown": _breakdown(
            core,
            "difficulty",
            (DifficultyLevel.EASY, DifficultyLevel.MEDIUM, DifficultyLevel.HARD),
        ),
        "question_type_breakdown": _breakdown(
            core, "question_type", QuestionType.values
        ),
        "time": _time_summary(core),
        "policy_version": "ar09-v1",
    }
