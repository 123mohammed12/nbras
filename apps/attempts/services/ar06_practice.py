"""AR-06 wrong-answer evidence and deterministic weakness practice."""

from __future__ import annotations

import copy
import random
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, When
from django.utils import timezone

from apps.assessments.models import AssessmentType
from apps.attempts.models import (
    AssessmentAttempt,
    AttemptAnswer,
    AttemptMode,
    AttemptQuestion,
    AttemptStatus,
    AttemptType,
    QuestionPerformanceEvent,
    QuestionPerformanceEvidence,
)
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, Lesson, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import check_resources_access_batch
from apps.question_bank.models import SourceType


FINAL_STATUSES = (
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
    AttemptStatus.EXPIRED,
)
WEAKNESS_DIMENSIONS = ("subject", "unit", "lesson", "difficulty", "question_type", "source")


def _active_enrollment(user):
    enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
    if enrollment is None:
        raise ApplicationError("No active enrollment.", code="NO_ACTIVE_ENROLLMENT")
    return enrollment


def validate_practice_scope(*, user, subject_id, unit_id=None, lesson_id=None):
    enrollment = _active_enrollment(user)
    subject = Subject.objects.filter(
        id=subject_id,
        status=ContentStatus.PUBLISHED,
        grade_id=enrollment.grade_id,
        section_id=enrollment.section_id,
    ).first()
    if subject is None:
        raise ApplicationError("Practice scope is invalid.", code="WEAKNESS_SCOPE_INVALID")
    unit = None
    lesson = None
    if lesson_id:
        lesson = Lesson.objects.filter(
            id=lesson_id,
            unit__subject=subject,
            status=ContentStatus.PUBLISHED,
            unit__status=ContentStatus.PUBLISHED,
        ).select_related("unit").first()
        if lesson is None or (unit_id and str(lesson.unit_id) != str(unit_id)):
            raise ApplicationError("Practice scope is invalid.", code="WEAKNESS_SCOPE_INVALID")
        unit = lesson.unit
        resource = {"type": "lesson", "id": lesson.id}
    elif unit_id:
        unit = Unit.objects.filter(
            id=unit_id, subject=subject, status=ContentStatus.PUBLISHED,
        ).first()
        if unit is None:
            raise ApplicationError("Practice scope is invalid.", code="WEAKNESS_SCOPE_INVALID")
        resource = {"type": "unit", "id": unit.id}
    else:
        resource = {"type": "subject", "id": subject.id}
    decisions = check_resources_access_batch(
        user=user, enrollment=enrollment, resources=[resource],
    )
    if not decisions[(resource["type"], str(resource["id"]))].allowed:
        raise ApplicationError(
            "Practice scope is inaccessible.", code="INACCESSIBLE_SCOPE", status_code=403,
        )
    return enrollment, subject, unit, lesson


def _identity_for(attempt_question):
    question = attempt_question.question_version.question
    if attempt_question.source_type == SourceType.MINISTERIAL and attempt_question.ministerial_exam_item_id:
        return f"ministerial:{attempt_question.ministerial_exam_item_id}"
    return f"{attempt_question.source_type}:question:{question.id}"


def _answer_outcome(answer, maximum):
    awarded = Decimal(answer.awarded_points)
    maximum = Decimal(maximum)
    if answer.is_correct is True or (maximum > 0 and awarded >= maximum):
        return "correct"
    if awarded > 0:
        return "partial"
    return "incorrect"


def _has_submitted_answer(answer):
    return bool(
        answer
        and (
            answer.selected_option_id
            or answer.selected_option_key
            or answer.answer_text
            or answer.answer_payload
        )
    )


def _recalculate_exact_evidence(evidence):
    """Replace the collapsed AR-06 identity projection from its idempotent events."""
    events = list(
        evidence.events.select_related(
            "attempt_question__attempt",
            "attempt_question__question_version__question",
            "attempt_question__ministerial_exam_item",
        ).order_by("occurred_at", "pk")
    )
    if not events:
        evidence.delete()
        return
    wrong_count = 0
    correct_count = 0
    correct_after_wrong_count = 0
    last_wrong = None
    last_practiced_at = None
    had_wrong = False
    for event in events:
        if event.outcome in ("incorrect", "partial"):
            wrong_count += 1
            had_wrong = True
            last_wrong = event
        else:
            correct_count += 1
            if had_wrong:
                correct_after_wrong_count += 1
        if event.attempt_question.attempt.dynamic_assessment_type == AssessmentType.WRONG_ANSWERS_TEST:
            last_practiced_at = event.occurred_at
    latest = events[-1]
    aq = latest.attempt_question
    question = aq.question_version.question
    evidence.source_type = aq.source_type
    evidence.question = question
    evidence.question_version = aq.question_version
    evidence.ministerial_exam_item = aq.ministerial_exam_item
    evidence.subject = question.subject
    evidence.unit = question.unit
    evidence.lesson = question.lesson
    evidence.difficulty = question.difficulty
    evidence.question_type = question.question_type
    evidence.wrong_count = wrong_count
    evidence.correct_count = correct_count
    evidence.correct_after_wrong_count = correct_after_wrong_count
    evidence.last_outcome = latest.outcome
    evidence.last_awarded_points = latest.awarded_points
    evidence.last_maximum_points = latest.maximum_points
    evidence.last_attempt_question = aq
    evidence.last_seen_at = latest.occurred_at
    evidence.last_wrong_attempt_question = last_wrong.attempt_question if last_wrong else None
    evidence.last_wrong_at = last_wrong.occurred_at if last_wrong else None
    evidence.last_practiced_at = last_practiced_at
    evidence.save()


@transaction.atomic
def project_attempt_evidence(attempt, *, refresh_mastery=True):
    """Upsert finalized question grades; later grade changes replace the same event."""
    if attempt.status not in FINAL_STATUSES:
        return 0
    questions = list(
        AttemptQuestion.objects.filter(attempt=attempt, is_reference=False)
        .select_related("question_version__question")
    )
    answers = {
        row.attempt_question_id: row
        for row in AttemptAnswer.objects.filter(
            attempt=attempt, is_correct__isnull=False, is_evaluated=True,
        )
    }
    occurred_at = attempt.evaluated_at or attempt.submitted_at or timezone.now()
    projected = 0
    for aq in questions:
        answer = answers.get(aq.id)
        if not _has_submitted_answer(answer) or Decimal(aq.points) <= 0:
            continue
        question = aq.question_version.question
        outcome = _answer_outcome(answer, aq.points)
        identity_key = _identity_for(aq)
        evidence, _ = QuestionPerformanceEvidence.objects.select_for_update().get_or_create(
            user=attempt.user,
            study_enrollment=attempt.study_enrollment,
            identity_key=identity_key,
            defaults={
                "source_type": aq.source_type,
                "question": question,
                "question_version": aq.question_version,
                "ministerial_exam_item": aq.ministerial_exam_item,
                "subject": question.subject,
                "unit": question.unit,
                "lesson": question.lesson,
                "difficulty": question.difficulty,
                "question_type": question.question_type,
                "last_attempt_question": aq,
                "last_seen_at": occurred_at,
            },
        )
        values = {
            "evidence": evidence,
            "outcome": outcome,
            "awarded_points": answer.awarded_points,
            "maximum_points": aq.points,
            "occurred_at": occurred_at,
        }
        existing = QuestionPerformanceEvent.objects.filter(attempt_question=aq).first()
        if existing is not None and all(
            getattr(existing, field) == value for field, value in values.items()
        ):
            continue
        QuestionPerformanceEvent.objects.update_or_create(
            attempt_question=aq, defaults=values,
        )
        _recalculate_exact_evidence(evidence)
        projected += 1
    if projected and refresh_mastery:
        from apps.progress.services.mastery import rebuild_mastery_for_evidence
        rebuild_mastery_for_evidence(
            user=attempt.user,
            enrollment=attempt.study_enrollment,
            subject_ids={row.question_version.question.subject_id for row in questions},
            unit_ids={row.question_version.question.unit_id for row in questions},
            lesson_ids={row.question_version.question.lesson_id for row in questions},
        )
    return projected


@transaction.atomic
def rebuild_question_performance_evidence(*, user=None, enrollment=None):
    events = QuestionPerformanceEvent.objects.all()
    evidence = QuestionPerformanceEvidence.objects.all()
    attempts = AssessmentAttempt.objects.filter(status__in=FINAL_STATUSES).order_by("submitted_at", "created_at")
    if user is not None:
        events = events.filter(attempt_question__attempt__user=user)
        evidence = evidence.filter(user=user)
        attempts = attempts.filter(user=user)
    if enrollment is not None:
        events = events.filter(attempt_question__attempt__study_enrollment=enrollment)
        evidence = evidence.filter(study_enrollment=enrollment)
        attempts = attempts.filter(study_enrollment=enrollment)
    events.delete()
    evidence.delete()
    projected = sum(
        project_attempt_evidence(attempt, refresh_mastery=False)
        for attempt in attempts.iterator()
    )
    from apps.progress.services.mastery import rebuild_mastery_read_models
    rebuild_mastery_read_models(user=user, enrollment=enrollment)
    return projected


def _scope_evidence(*, user, enrollment, subject, unit=None, lesson=None):
    query = QuestionPerformanceEvidence.objects.filter(
        user=user, study_enrollment=enrollment, subject=subject,
    )
    if lesson is not None:
        query = query.filter(lesson=lesson)
    elif unit is not None:
        query = query.filter(unit=unit)
    return query


def wrong_answer_summary(*, user, subject_id, unit_id=None, lesson_id=None, limit=20):
    enrollment, subject, unit, lesson = validate_practice_scope(
        user=user, subject_id=subject_id, unit_id=unit_id, lesson_id=lesson_id,
    )
    query = _scope_evidence(
        user=user, enrollment=enrollment, subject=subject, unit=unit, lesson=lesson,
    ).filter(wrong_count__gt=0, last_wrong_attempt_question__isnull=False)
    bounded = max(1, min(int(limit), 50))
    ranked = query.annotate(
        unresolved=Case(
            When(last_outcome__in=("incorrect", "partial"), then=1),
            default=0,
            output_field=IntegerField(),
        )
    ).select_related("last_wrong_attempt_question").order_by(
        "-unresolved", "-wrong_count", "-last_wrong_at", "last_practiced_at", "identity_key",
    )
    rows = list(ranked[:bounded])
    breakdown = {
        row["source_type"]: row["count"]
        for row in query.values("source_type").annotate(count=Count("id"))
    }
    return {
        "scope": {
            "subject_id": str(subject.id),
            "unit_id": str(unit.id) if unit else None,
            "lesson_id": str(lesson.id) if lesson else None,
        },
        "total_wrong_questions": query.count(),
        "source_breakdown": breakdown,
        "items": [
            {
                "identity": row.identity_key,
                "source": row.source_type,
                "wrong_count": row.wrong_count,
                "correct_after_wrong_count": row.correct_after_wrong_count,
                "last_outcome": row.last_outcome,
                "last_seen_at": row.last_seen_at,
                "last_wrong_at": row.last_wrong_at,
            }
            for row in rows
        ],
    }


def _assert_question_access(*, user, enrollment, questions):
    resources = {}
    for aq in questions:
        question = aq.question_version.question
        if str(question.subject.grade_id) != str(enrollment.grade_id) or str(question.subject.section_id) != str(enrollment.section_id):
            raise ApplicationError("Question is outside the active enrollment.", code="INACCESSIBLE_SCOPE", status_code=403)
        if question.lesson_id:
            resources[("lesson", str(question.lesson_id))] = {"type": "lesson", "id": question.lesson_id}
        elif question.unit_id:
            resources[("unit", str(question.unit_id))] = {"type": "unit", "id": question.unit_id}
        else:
            resources[("subject", str(question.subject_id))] = {"type": "subject", "id": question.subject_id}
    decisions = check_resources_access_batch(
        user=user, enrollment=enrollment, resources=list(resources.values()),
    )
    denied = [key[1] for key in resources if not decisions[key].allowed]
    if denied:
        raise ApplicationError(
            "Wrong-answer practice contains inaccessible questions.",
            code="INACCESSIBLE_SCOPE", status_code=403,
            fields={"resource_ids": denied},
        )


def _eligible_wrong_questions(parent):
    if parent.status not in FINAL_STATUSES:
        raise ApplicationError("The source attempt is not finalized.", code="WRONG_PRACTICE_INVALID")
    return list(
        AttemptQuestion.objects.filter(
            attempt=parent,
            is_reference=False,
            answers__is_correct=False,
            answers__awarded_points=Decimal("0"),
        ).exclude(
            Q(answers__selected_option_id__isnull=True)
            & Q(answers__selected_option_key__isnull=True)
            & Q(answers__answer_text="")
            & Q(answers__answer_payload={})
        ).select_related(
            "question_version__question", "assessment_item", "ministerial_exam_item",
        ).order_by("sort_order")
    )


@transaction.atomic
def _freeze_exact_wrong_attempt(*, user, enrollment, questions, parent=None, scope=None):
    if not questions:
        raise ApplicationError("No eligible wrong answers.", code="NO_WRONG_ANSWERS")
    _assert_question_access(user=user, enrollment=enrollment, questions=questions)
    if parent is not None:
        existing = AssessmentAttempt.objects.filter(
            parent_attempt=parent,
            user=user,
            dynamic_assessment_type=AssessmentType.WRONG_ANSWERS_TEST,
            status__in=(AttemptStatus.CREATED, AttemptStatus.IN_PROGRESS, AttemptStatus.PAUSED),
        ).order_by("-created_at").first()
        if existing is not None:
            return existing
    frozen = list(questions)
    random.shuffle(frozen)
    subject = frozen[0].question_version.question.subject
    attempt = AssessmentAttempt.objects.create(
        user=user,
        study_enrollment=enrollment,
        assessment=parent.assessment if parent is not None else None,
        assessment_version=parent.assessment_version if parent is not None else None,
        parent_attempt=parent,
        attempt_type=AttemptType.WRONG_ANSWERS,
        mode=AttemptMode.PRACTICE,
        status=AttemptStatus.IN_PROGRESS,
        display_mode="single",
        contract_version=1,
        source_scope={"kind": AssessmentType.WRONG_ANSWERS_TEST, **(scope or {})},
        dynamic_assessment_type=AssessmentType.WRONG_ANSWERS_TEST,
        dynamic_title="تدريب على الأخطاء",
        dynamic_subject=subject,
        selection_spec_snapshot={
            "strategy": "wrong_exact_snapshot_set",
            "count": len(frozen),
            "identities": [_identity_for(aq) for aq in frozen],
        },
        selection_policy_snapshot={"engine": "shared_attempt_freezer", "exact_set": True},
        feedback_policy="immediate",
        timing_mode="none",
        questions_shuffled=True,
        options_shuffled=True,
    )
    copied = []
    total = Decimal("0")
    for index, original in enumerate(frozen, 1):
        snapshot = copy.deepcopy(original.question_snapshot)
        options = list(snapshot.get("options") or [])
        if snapshot.get("question_type") != "true_false":
            random.shuffle(options)
            snapshot["options"] = options
        copied.append(AttemptQuestion(
            attempt=attempt,
            question_version=original.question_version,
            assessment_item=original.assessment_item,
            ministerial_exam_item=original.ministerial_exam_item,
            source_type=original.source_type,
            sort_order=index,
            points=original.points,
            is_reference=False,
            options_order_snapshot=[str(option.get("option_key", "")) for option in options],
            source_metadata_snapshot=copy.deepcopy(original.source_metadata_snapshot),
            question_snapshot=snapshot,
        ))
        total += original.points
    AttemptQuestion.objects.bulk_create(copied)
    attempt.maximum_score = total
    attempt.official_maximum_score = total
    attempt.save(update_fields=["maximum_score", "official_maximum_score"])
    return attempt


def create_per_attempt_wrong_practice(*, user, parent_attempt_id):
    parent = AssessmentAttempt.objects.filter(id=parent_attempt_id, user=user).first()
    if parent is None:
        raise ApplicationError("The source attempt was not found.", code="WRONG_PRACTICE_INVALID")
    questions = _eligible_wrong_questions(parent)
    enrollment = _active_enrollment(user)
    return _freeze_exact_wrong_attempt(
        user=user,
        enrollment=enrollment,
        questions=questions,
        parent=parent,
        scope={"parent_attempt_id": str(parent.id)},
    )


def create_global_wrong_practice(*, user, subject_id, unit_id=None, lesson_id=None, count=15):
    enrollment, subject, unit, lesson = validate_practice_scope(
        user=user, subject_id=subject_id, unit_id=unit_id, lesson_id=lesson_id,
    )
    target = max(1, min(int(count), 20))
    query = _scope_evidence(
        user=user, enrollment=enrollment, subject=subject, unit=unit, lesson=lesson,
    ).filter(wrong_count__gt=0, last_wrong_attempt_question__isnull=False).annotate(
        unresolved=Case(
            When(last_outcome__in=("incorrect", "partial"), then=1),
            default=0,
            output_field=IntegerField(),
        )
    ).select_related(
        "last_wrong_attempt_question__question_version__question",
        "last_wrong_attempt_question__assessment_item",
        "last_wrong_attempt_question__ministerial_exam_item",
    ).order_by("-unresolved", "-wrong_count", "-last_wrong_at", "last_practiced_at", "identity_key")
    questions = [row.last_wrong_attempt_question for row in query[:target]]
    return _freeze_exact_wrong_attempt(
        user=user,
        enrollment=enrollment,
        questions=questions,
        scope={
            "subject_id": str(subject.id),
            "unit_id": str(unit.id) if unit else None,
            "lesson_id": str(lesson.id) if lesson else None,
            "global": True,
        },
    )


def weakness_signals(*, user, subject_id, unit_id=None, lesson_id=None):
    enrollment, subject, unit, lesson = validate_practice_scope(
        user=user, subject_id=subject_id, unit_id=unit_id, lesson_id=lesson_id,
    )
    from apps.progress.services.mastery import mastery_weakness_signals
    return mastery_weakness_signals(
        user=user,
        enrollment=enrollment,
        subject=subject,
        unit=unit,
        lesson=lesson,
    )


def create_weakness_practice(
    *, user, subject_id, dimension, value, unit_id=None, lesson_id=None,
    source=SourceType.TRAINING, count=10,
):
    if dimension not in WEAKNESS_DIMENSIONS:
        raise ApplicationError("Weakness dimension is invalid.", code="WEAKNESS_SCOPE_INVALID")
    summary = weakness_signals(
        user=user, subject_id=subject_id, unit_id=unit_id, lesson_id=lesson_id,
    )
    signal = next(
        (row for row in summary["signals"] if row["dimension"] == dimension and row["value"] == str(value)),
        None,
    )
    if signal is None:
        raise ApplicationError(
            "There is not enough reliable evidence for this weakness.",
            code="INSUFFICIENT_WEAKNESS_EVIDENCE",
        )
    sources = [source]
    if source not in (SourceType.TRAINING, SourceType.MINISTERIAL):
        raise ApplicationError("Weakness source is invalid.", code="WEAKNESS_SCOPE_INVALID")
    if dimension == "source":
        sources = [value]
    scope_mode = "subject"
    unit_ids = []
    lesson_ids = []
    if lesson_id:
        scope_mode, lesson_ids = "lessons", [str(lesson_id)]
    elif unit_id:
        scope_mode, unit_ids = "units", [str(unit_id)]
    if dimension == "lesson":
        scope_mode, unit_ids, lesson_ids = "lessons", [], [str(value)]
    elif dimension == "unit":
        scope_mode, unit_ids, lesson_ids = "units", [str(value)], []
    elif dimension == "subject" and str(value) != str(subject_id):
        raise ApplicationError("Weakness scope is invalid.", code="WEAKNESS_SCOPE_INVALID")
    target = max(1, min(int(count), 20))
    payload = {
        "subject_id": str(subject_id),
        "scope": {"mode": scope_mode, "unit_ids": unit_ids, "lesson_ids": lesson_ids},
        "sources": sources,
        "years": [],
        "difficulties": [str(value)] if dimension == "difficulty" else ["easy", "medium", "hard"],
        "question_types": [str(value)] if dimension == "question_type" else ["multiple_choice", "true_false"],
        "count": target,
        "mode": "practice",
        "exclude_previously_answered": True,
    }
    from apps.attempts.services.custom_tests import create_custom_test, preview_custom_test

    preview = preview_custom_test(user=user, payload=payload)
    available = preview["maximum_creatable"]
    if available <= 0:
        raise ApplicationError(
            "No questions are available inside the weak scope.",
            code="WEAKNESS_POOL_INSUFFICIENT",
            fields={"requested": target, "available": 0},
        )
    actual = min(target, available)
    payload["count"] = actual
    return create_custom_test(
        user=user,
        payload=payload,
        dynamic_assessment_type="weakness_practice",
        dynamic_title="تدريب على نقاط الضعف",
        source_scope_extra={
            "weakness_dimension": dimension,
            "weakness_value": str(value),
        },
        selection_policy_extra={
            "weakness_signal": signal,
            "requested_count": target,
            "shortage": target - actual,
        },
    )


def preferred_weakness_for_attempt(*, user, attempt):
    question = attempt.attempt_questions.select_related("question_version__question").first()
    if question is None:
        return None
    academic = question.question_version.question
    try:
        summary = weakness_signals(
            user=user,
            subject_id=str(academic.subject_id),
            unit_id=str(academic.unit_id) if academic.unit_id else None,
            lesson_id=str(academic.lesson_id) if academic.lesson_id else None,
        )
    except ApplicationError:
        return None
    return summary["signals"][0] if summary["signals"] else None
