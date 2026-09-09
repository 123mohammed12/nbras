from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from apps.analytics.models import QuestionQualityAggregate, QuestionQualityContribution
from apps.analytics.services.quality_policy import get_question_quality_policy
from apps.assessments.models import AssessmentType
from apps.attempts.models import (
    AssessmentAttempt,
    AttemptAnswer,
    AttemptQuestion,
    AttemptStatus,
    AttemptType,
)
from apps.question_bank.models import QuestionType, SourceType


FINAL_STATUSES = (
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
    AttemptStatus.EXPIRED,
)
REMEDIATION_ASSESSMENT_KINDS = (
    AssessmentType.WRONG_ANSWERS_TEST,
    "weakness_practice",
)


def question_quality_identity(attempt_question: AttemptQuestion) -> str:
    version_id = str(attempt_question.question_version_id)
    if (
        attempt_question.source_type == SourceType.MINISTERIAL
        and attempt_question.ministerial_exam_item_id
    ):
        return (
            f"ministerial:{attempt_question.ministerial_exam_item_id}:"
            f"version:{version_id}"
        )
    return f"version:{version_id}"


def _assessment_kind(attempt: AssessmentAttempt) -> str:
    return attempt.dynamic_assessment_type or (
        attempt.assessment.assessment_type if attempt.assessment_id else ""
    )


def _is_remediation(attempt: AssessmentAttempt) -> bool:
    return (
        attempt.attempt_type == AttemptType.WRONG_ANSWERS
        or _assessment_kind(attempt) in REMEDIATION_ASSESSMENT_KINDS
    )


def _has_answer(answer: AttemptAnswer | None) -> bool:
    return bool(
        answer
        and (
            answer.selected_option_id
            or answer.selected_option_key
            or answer.answer_text
            or answer.answer_payload
        )
    )


def _is_auto_gradable(snapshot: dict) -> bool:
    question_type = snapshot.get("question_type", QuestionType.MULTIPLE_CHOICE)
    if question_type in (
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.TRUE_FALSE,
        QuestionType.MULTIPLE_SELECT,
    ):
        return True
    if question_type == QuestionType.NUMERIC:
        return snapshot.get("expected_value") is not None
    if question_type == QuestionType.SHORT_ANSWER:
        return bool(snapshot.get("accepted_answers"))
    return False


def _contribution_values(attempt, attempt_question, answer):
    snapshot = attempt_question.question_snapshot or {}
    question = attempt_question.question_version.question
    was_answered = _has_answer(answer)
    maximum = Decimal(attempt_question.points)
    awarded = Decimal("0")
    if not was_answered:
        outcome = "unanswered"
        maximum_gradable = maximum if _is_auto_gradable(snapshot) else Decimal("0")
    elif answer.is_evaluated and answer.is_correct is not None:
        awarded = Decimal(answer.awarded_points)
        maximum_gradable = maximum
        if answer.is_correct is True or (maximum > 0 and awarded >= maximum):
            outcome = "correct"
        elif awarded > 0:
            outcome = "partial"
        else:
            outcome = "incorrect"
    else:
        outcome = "pending"
        maximum_gradable = Decimal("0")

    selected_option_key = None
    if answer:
        selected_option_key = answer.selected_option_key or (
            (answer.answer_payload or {}).get("selected_option_key")
        )
    option_rows = snapshot.get("options") or []
    option_keys = [
        str(row.get("option_key")) for row in option_rows if row.get("option_key")
    ]
    correct_keys = [
        str(row.get("option_key"))
        for row in option_rows
        if row.get("option_key") and row.get("is_correct") is True
    ]
    if not correct_keys:
        correct_keys = [str(value) for value in snapshot.get("correct_option_keys") or []]
        if not correct_keys and snapshot.get("correct_option_key"):
            correct_keys = [str(snapshot["correct_option_key"])]

    return {
        "user": attempt.user,
        "study_enrollment": attempt.study_enrollment,
        "identity_key": question_quality_identity(attempt_question),
        "question_version": attempt_question.question_version,
        "ministerial_exam_item": attempt_question.ministerial_exam_item,
        "subject": question.subject,
        "unit": question.unit,
        "lesson": question.lesson,
        "source_type": attempt_question.source_type,
        "difficulty": snapshot.get("difficulty") or question.difficulty,
        "question_type": snapshot.get("question_type") or question.question_type,
        "assessment_kind": _assessment_kind(attempt),
        "attempt_type": attempt.attempt_type,
        "is_remediation": _is_remediation(attempt),
        "outcome": outcome,
        "was_answered": was_answered,
        "awarded_points": awarded,
        "maximum_gradable_points": maximum_gradable,
        "response_time_seconds": (
            answer.response_time_seconds
            if answer and answer.response_time_seconds > 0
            else None
        ),
        "selected_option_key": str(selected_option_key) if selected_option_key else None,
        "option_keys_snapshot": option_keys,
        "correct_option_keys_snapshot": correct_keys,
        "occurred_at": attempt.evaluated_at or attempt.submitted_at or timezone.now(),
    }


def _quality_flags(*, counts, option_distribution, question_type):
    policy = get_question_quality_policy()
    sample_size = counts["sample_size"]
    if sample_size < policy.minimum_sample_size:
        return []
    flags = []
    correct_rate = Decimal(counts["correct_count"]) / Decimal(sample_size)
    if correct_rate >= policy.very_high_correct_rate:
        flags.append("VERY_HIGH_CORRECT_RATE")
    if correct_rate <= policy.very_low_correct_rate:
        flags.append("VERY_LOW_CORRECT_RATE")
    if counts["presented_count"]:
        skip_rate = Decimal(counts["unanswered_count"]) / Decimal(
            counts["presented_count"]
        )
        if skip_rate >= policy.high_skip_rate:
            flags.append("HIGH_SKIP_RATE")

    if question_type == QuestionType.MULTIPLE_CHOICE:
        selected_total = sum(row["count"] for row in option_distribution.values())
        wrong_rows = [
            row for row in option_distribution.values() if not row.get("is_correct", False)
        ]
        if selected_total and any(
            Decimal(row["count"]) / Decimal(selected_total)
            <= policy.ineffective_distractor_rate
            for row in wrong_rows
        ):
            flags.append("INEFFECTIVE_DISTRACTOR")
        if selected_total and any(
            Decimal(row["count"]) / Decimal(selected_total)
            >= policy.answer_key_issue_wrong_option_rate
            for row in wrong_rows
        ):
            flags.append("POTENTIAL_ANSWER_KEY_ISSUE")
    return flags


@transaction.atomic
def rebuild_quality_aggregate(identity_key: str):
    # Remediation is intentionally retained in the contribution ledger for the
    # student's separate remediation view, but excluded from editorial quality:
    # targeted wrong/weakness sampling would otherwise bias global item quality.
    contributions = QuestionQualityContribution.objects.filter(
        identity_key=identity_key, is_remediation=False
    )
    seed = contributions.select_related(
        "question_version__question", "ministerial_exam_item"
    ).first()
    if seed is None:
        QuestionQualityAggregate.objects.filter(identity_key=identity_key).delete()
        return None

    totals = contributions.aggregate(
        presented_count=Count("id"),
        answered_count=Count("id", filter=Q(was_answered=True)),
        correct_count=Count("id", filter=Q(outcome="correct")),
        incorrect_count=Count("id", filter=Q(outcome="incorrect")),
        partial_count=Count("id", filter=Q(outcome="partial")),
        unanswered_count=Count("id", filter=Q(outcome="unanswered")),
        pending_count=Count("id", filter=Q(outcome="pending")),
        earned_points=Sum("awarded_points"),
        maximum_gradable_points=Sum("maximum_gradable_points"),
        response_time_total_seconds=Sum("response_time_seconds"),
        response_time_sample_count=Count(
            "id", filter=Q(response_time_seconds__isnull=False)
        ),
        first_finalized_at=Min("occurred_at"),
        last_finalized_at=Max("occurred_at"),
    )
    totals["sample_size"] = (
        totals["correct_count"] + totals["incorrect_count"] + totals["partial_count"]
    )
    policy = get_question_quality_policy()
    totals["sample_state"] = (
        "sufficient"
        if totals["sample_size"] >= policy.minimum_sample_size
        else "insufficient"
    )
    totals["earned_points"] = totals["earned_points"] or Decimal("0")
    totals["maximum_gradable_points"] = (
        totals["maximum_gradable_points"] or Decimal("0")
    )
    totals["response_time_total_seconds"] = (
        totals["response_time_total_seconds"] or 0
    )

    option_keys = set()
    correct_keys = set()
    for option_snapshot, correct_snapshot in contributions.values_list(
        "option_keys_snapshot", "correct_option_keys_snapshot"
    ).distinct():
        option_keys.update(str(value) for value in option_snapshot or [])
        correct_keys.update(str(value) for value in correct_snapshot or [])
    selected_counts = dict(
        contributions.exclude(selected_option_key__isnull=True)
        .exclude(selected_option_key="")
        .values_list("selected_option_key")
        .annotate(count=Count("id"))
    )
    selected_total = sum(selected_counts.values())
    option_distribution = {
        key: {
            "count": selected_counts.get(key, 0),
            "percentage": (
                round(selected_counts.get(key, 0) * 100 / selected_total, 2)
                if selected_total
                else None
            ),
            "is_correct": key in correct_keys,
        }
        for key in sorted(option_keys | set(selected_counts))
    }
    totals["option_distribution"] = option_distribution
    totals["quality_flags"] = _quality_flags(
        counts=totals,
        option_distribution=option_distribution,
        question_type=seed.question_type,
    )
    aggregate, _ = QuestionQualityAggregate.objects.update_or_create(
        identity_key=identity_key,
        defaults={
            "question_version": seed.question_version,
            "ministerial_exam_item": seed.ministerial_exam_item,
            "subject": seed.subject,
            "unit": seed.unit,
            "lesson": seed.lesson,
            "source_type": seed.source_type,
            "difficulty": seed.difficulty,
            "question_type": seed.question_type,
            **totals,
        },
    )
    return aggregate


@transaction.atomic
def project_attempt_question_quality(attempt: AssessmentAttempt) -> int:
    """Upsert finalized contributions; repeated processing and grade changes are safe."""
    if attempt.status not in FINAL_STATUSES or attempt.submitted_at is None:
        return 0
    questions = list(
        AttemptQuestion.objects.filter(attempt=attempt, is_reference=False)
        .select_related(
            "question_version__question",
            "ministerial_exam_item",
            "attempt__assessment",
        )
        .order_by("sort_order")
    )
    answers = {
        row.attempt_question_id: row
        for row in AttemptAnswer.objects.filter(attempt=attempt)
    }
    changed = 0
    touched = set()
    for question in questions:
        values = _contribution_values(attempt, question, answers.get(question.id))
        existing = QuestionQualityContribution.objects.filter(
            attempt_question=question
        ).first()
        old_identity = existing.identity_key if existing else None
        comparable = {
            field: (getattr(value, "pk", value) if value is not None else None)
            for field, value in values.items()
        }
        if existing is not None and all(
            (getattr(getattr(existing, field), "pk", getattr(existing, field)) if getattr(existing, field) is not None else None)
            == value
            for field, value in comparable.items()
        ):
            continue
        QuestionQualityContribution.objects.update_or_create(
            attempt_question=question, defaults=values
        )
        changed += 1
        touched.add(values["identity_key"])
        if old_identity:
            touched.add(old_identity)
    for identity_key in touched:
        rebuild_quality_aggregate(identity_key)
    return changed


@transaction.atomic
def rebuild_question_quality(*, user=None, enrollment=None) -> int:
    contributions = QuestionQualityContribution.objects.all()
    attempts = AssessmentAttempt.objects.filter(
        status__in=FINAL_STATUSES, submitted_at__isnull=False
    ).order_by("submitted_at", "created_at")
    if user is not None:
        contributions = contributions.filter(user=user)
        attempts = attempts.filter(user=user)
    if enrollment is not None:
        contributions = contributions.filter(study_enrollment=enrollment)
        attempts = attempts.filter(study_enrollment=enrollment)

    affected_identities = set(contributions.values_list("identity_key", flat=True))
    contributions.delete()
    changed = sum(
        project_attempt_question_quality(attempt) for attempt in attempts.iterator()
    )
    for identity_key in affected_identities:
        if not QuestionQualityContribution.objects.filter(
            identity_key=identity_key
        ).exists():
            QuestionQualityAggregate.objects.filter(identity_key=identity_key).delete()
    return changed
