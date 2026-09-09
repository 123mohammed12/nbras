from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Prefetch
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.assessments.models import AssessmentType
from apps.attempts.models import QuestionPerformanceEvent, QuestionPerformanceEvidence
from apps.curriculum.models import Lesson, Subject, Unit
from apps.curriculum.models import StudyEnrollment
from apps.progress.models import MasteryAggregate, MasteryScopeType
from apps.progress.services.mastery_policy import MasteryPolicy, get_mastery_policy


REMEDIATION_TYPES = {
    AssessmentType.WRONG_ANSWERS_TEST,
    "weakness_practice",
}


@dataclass(frozen=True)
class IdentityContribution:
    ratio: Decimal
    weight: Decimal
    source: str
    difficulty: str
    question_type: str
    occurred_at: object
    events: tuple


def _ratio(event) -> Decimal:
    maximum = Decimal(event.maximum_points)
    if maximum <= 0:
        return Decimal("0")
    earned = max(Decimal("0"), min(Decimal(event.awarded_points), maximum))
    return earned / maximum


def _is_remediation(event) -> bool:
    attempt = event.attempt_question.attempt
    return (
        attempt.dynamic_assessment_type in REMEDIATION_TYPES
        or attempt.attempt_type == "wrong_answers"
    )


def _recency_weight(occurred_at, now, policy: MasteryPolicy) -> Decimal:
    age = max(0, (now - occurred_at).days)
    if age <= policy.recent_days:
        return policy.recent_weight
    if age <= policy.prior_days:
        return policy.prior_weight
    if age <= policy.older_days:
        return policy.older_weight
    return policy.historical_weight


def _identity_contribution(evidence, now, policy: MasteryPolicy):
    events = tuple(
        event for event in evidence.events.all()
        if Decimal(event.maximum_points) > 0
    )
    if not events:
        return None
    baseline = next((event for event in reversed(events) if not _is_remediation(event)), None)
    latest = events[-1]
    if baseline is None or not _is_remediation(latest) or latest.occurred_at <= baseline.occurred_at:
        score = _ratio(latest if baseline is None else baseline)
        effective_at = latest.occurred_at if baseline is None else baseline.occurred_at
    else:
        share = policy.remediation_share
        score = (_ratio(baseline) * (Decimal("1") - share)) + (_ratio(latest) * share)
        effective_at = latest.occurred_at
    return IdentityContribution(
        ratio=score,
        weight=_recency_weight(effective_at, now, policy),
        source=evidence.source_type,
        difficulty=evidence.difficulty,
        question_type=evidence.question_type,
        occurred_at=effective_at,
        events=events,
    )


def _confidence(distinct: int, policy: MasteryPolicy) -> str:
    if distinct <= 0:
        return "insufficient"
    if distinct < policy.moderate_confidence_min:
        return "limited"
    if distinct < policy.strong_confidence_min:
        return "moderate"
    return "strong"


def _weakness(score, distinct, effective, policy: MasteryPolicy):
    if score is None:
        return "unknown", "", "no_reliable_graded_evidence"
    if distinct < policy.weakness_min_distinct or effective < policy.weakness_min_effective:
        return "needs_more_evidence", "", "insufficient_distinct_or_recent_evidence"
    if score <= policy.weakness_max_score:
        priority = "high" if score <= policy.high_priority_max_score else "medium"
        return "actionable", priority, "low_mastery_with_sufficient_current_evidence"
    return "not_weakness", "", "mastery_above_weakness_threshold"


def _breakdown(contributions, key, policy: MasteryPolicy):
    grouped = defaultdict(list)
    for item in contributions:
        grouped[getattr(item, key)].append(item)
    result = {}
    for value, rows in sorted(grouped.items()):
        distinct = len(rows)
        effective = sum((row.weight for row in rows), Decimal("0"))
        if distinct < policy.breakdown_min_distinct or effective <= 0:
            result[value] = {
                "state": "unknown",
                "mastery_score": None,
                "mastery_percent": None,
                "distinct_evidence_count": distinct,
                "effective_evidence": float(effective),
                "confidence": _confidence(distinct, policy),
                "weakness_status": "needs_more_evidence",
            }
            continue
        score = sum((row.ratio * row.weight for row in rows), Decimal("0")) / effective
        status, priority, reason = _weakness(score, distinct, effective, policy)
        result[value] = {
            "state": "known",
            "mastery_score": float(score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "mastery_percent": int((score * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            "distinct_evidence_count": distinct,
            "effective_evidence": float(effective.quantize(Decimal("0.0001"))),
            "confidence": _confidence(distinct, policy),
            "weakness_status": status,
            "priority": priority or None,
            "reason": reason,
        }
    return result


def _window_ratio(contributions, start, end, policy: MasteryPolicy):
    rows = []
    for contribution in contributions:
        candidates = [
            event for event in contribution.events
            if start <= event.occurred_at < end
        ]
        if candidates:
            latest = candidates[-1]
            rows.append((_ratio(latest), policy.remediation_share if _is_remediation(latest) else Decimal("1")))
    if len(rows) < policy.trend_min_distinct:
        return None
    total = sum((weight for _, weight in rows), Decimal("0"))
    return sum((score * weight for score, weight in rows), Decimal("0")) / total


def _trend(contributions, now, policy: MasteryPolicy) -> str:
    recent_start = now - timedelta(days=policy.recent_days)
    prior_start = now - timedelta(days=policy.prior_days)
    recent = _window_ratio(contributions, recent_start, now + timedelta(seconds=1), policy)
    prior = _window_ratio(contributions, prior_start, recent_start, policy)
    if recent is None or prior is None:
        return "insufficient_data"
    delta = recent - prior
    if delta >= policy.trend_delta:
        return "improving"
    if delta <= -policy.trend_delta:
        return "declining"
    return "stable"


def _evidence_query(*, user, enrollment, scope_type, scope_id):
    filters = {scope_type: scope_id}
    event_query = QuestionPerformanceEvent.objects.select_related(
        "attempt_question__attempt"
    ).order_by("occurred_at", "pk")
    return QuestionPerformanceEvidence.objects.filter(
        user=user,
        study_enrollment=enrollment,
        **filters,
    ).prefetch_related(Prefetch("events", queryset=event_query))


@transaction.atomic
def rebuild_mastery_scope(*, user, enrollment, scope_type, scope_id, now=None):
    if scope_type not in MasteryScopeType.values:
        raise ValueError("Unsupported mastery scope")
    policy = get_mastery_policy()
    now = now or timezone.now()
    contributions = [
        contribution
        for evidence in _evidence_query(
            user=user, enrollment=enrollment, scope_type=scope_type, scope_id=scope_id,
        )
        if (contribution := _identity_contribution(evidence, now, policy)) is not None
    ]
    if not contributions:
        MasteryAggregate.objects.filter(
            user=user, study_enrollment=enrollment, scope_type=scope_type, scope_id=str(scope_id),
        ).delete()
        return None
    effective = sum((item.weight for item in contributions), Decimal("0"))
    score = sum((item.ratio * item.weight for item in contributions), Decimal("0")) / effective
    distinct = len(contributions)
    weakness_status, priority, reason = _weakness(score, distinct, effective, policy)
    aggregate, _ = MasteryAggregate.objects.update_or_create(
        user=user,
        study_enrollment=enrollment,
        scope_type=scope_type,
        scope_id=str(scope_id),
        defaults={
            "mastery_score": score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "distinct_evidence_count": distinct,
            "effective_evidence": effective.quantize(Decimal("0.0001")),
            "confidence": _confidence(distinct, policy),
            "trend": _trend(contributions, now, policy),
            "weakness_status": weakness_status,
            "weakness_priority": priority,
            "weakness_reason": reason,
            "source_breakdown": _breakdown(contributions, "source", policy),
            "difficulty_breakdown": _breakdown(contributions, "difficulty", policy),
            "question_type_breakdown": _breakdown(contributions, "question_type", policy),
            "policy_version": policy.version,
            "calculated_at": now,
        },
    )
    return aggregate


def rebuild_mastery_for_evidence(*, user, enrollment, subject_ids, unit_ids, lesson_ids, now=None):
    rows = []
    for scope_type, ids in (
        (MasteryScopeType.SUBJECT, subject_ids),
        (MasteryScopeType.UNIT, unit_ids),
        (MasteryScopeType.LESSON, lesson_ids),
    ):
        for scope_id in sorted({str(value) for value in ids if value is not None}):
            row = rebuild_mastery_scope(
                user=user, enrollment=enrollment, scope_type=scope_type,
                scope_id=scope_id, now=now,
            )
            if row is not None:
                rows.append(row)
    return rows


@transaction.atomic
def rebuild_mastery_read_models(*, user=None, enrollment=None, now=None):
    aggregates = MasteryAggregate.objects.all()
    evidence = QuestionPerformanceEvidence.objects.all()
    if user is not None:
        aggregates = aggregates.filter(user=user)
        evidence = evidence.filter(user=user)
    if enrollment is not None:
        aggregates = aggregates.filter(study_enrollment=enrollment)
        evidence = evidence.filter(study_enrollment=enrollment)
    aggregates.delete()
    groups = defaultdict(lambda: {"subjects": set(), "units": set(), "lessons": set()})
    for row in evidence.values(
        "user_id", "study_enrollment_id", "subject_id", "unit_id", "lesson_id"
    ).iterator(chunk_size=500):
        key = (row["user_id"], row["study_enrollment_id"])
        groups[key]["subjects"].add(row["subject_id"])
        groups[key]["units"].add(row["unit_id"])
        groups[key]["lessons"].add(row["lesson_id"])
    count = 0
    for (user_id, enrollment_id), scopes in groups.items():
        scoped_user = get_user_model().objects.get(id=user_id)
        scoped_enrollment = StudyEnrollment.objects.get(id=enrollment_id)
        count += len(rebuild_mastery_for_evidence(
            user=scoped_user,
            enrollment=scoped_enrollment,
            subject_ids=scopes["subjects"],
            unit_ids=scopes["units"],
            lesson_ids=scopes["lessons"],
            now=now,
        ))
    return count


def unknown_mastery(*, scope_type, scope_id, title=None):
    return {
        "scope": {"type": scope_type, "id": str(scope_id), "title": title},
        "state": "unknown",
        "mastery_score": None,
        "mastery_percent": None,
        "confidence": "insufficient",
        "distinct_evidence_count": 0,
        "effective_evidence": 0.0,
        "trend": "insufficient_data",
        "source_breakdown": {},
        "difficulty_breakdown": {},
        "question_type_breakdown": {},
        "weakness_status": "unknown",
        "weakness_priority": None,
        "weakness_reason": "no_reliable_graded_evidence",
        "policy_version": get_mastery_policy().version,
    }


def serialize_mastery(aggregate, *, title=None):
    if aggregate is None:
        return None
    score = Decimal(aggregate.mastery_score)
    return {
        "scope": {"type": aggregate.scope_type, "id": aggregate.scope_id, "title": title},
        "state": "known",
        "mastery_score": float(score),
        "mastery_percent": int((score * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "confidence": aggregate.confidence,
        "distinct_evidence_count": aggregate.distinct_evidence_count,
        "effective_evidence": float(aggregate.effective_evidence),
        "trend": aggregate.trend,
        "source_breakdown": aggregate.source_breakdown,
        "difficulty_breakdown": aggregate.difficulty_breakdown,
        "question_type_breakdown": aggregate.question_type_breakdown,
        "weakness_status": aggregate.weakness_status,
        "weakness_priority": aggregate.weakness_priority or None,
        "weakness_reason": aggregate.weakness_reason,
        "policy_version": aggregate.policy_version,
    }


def mastery_for_scope(*, user, enrollment, scope_type, scope_id, title=None):
    aggregate = MasteryAggregate.objects.filter(
        user=user,
        study_enrollment=enrollment,
        scope_type=scope_type,
        scope_id=str(scope_id),
    ).first()
    return serialize_mastery(aggregate, title=title) or unknown_mastery(
        scope_type=scope_type, scope_id=scope_id, title=title,
    )


def mastery_overview(*, user, enrollment):
    rows = list(MasteryAggregate.objects.filter(
        user=user, study_enrollment=enrollment, scope_type=MasteryScopeType.SUBJECT,
    ))
    if not rows:
        result = unknown_mastery(scope_type="overview", scope_id=enrollment.id, title="Mastery")
        result["top_weakness"] = None
        return result
    effective = sum((Decimal(row.effective_evidence) for row in rows), Decimal("0"))
    score = sum(
        Decimal(row.mastery_score) * Decimal(row.effective_evidence) for row in rows
    ) / effective
    distinct = sum(row.distinct_evidence_count for row in rows)
    policy = get_mastery_policy()
    trend_weights = defaultdict(Decimal)
    for row in rows:
        trend_weights[row.trend] += Decimal(row.effective_evidence)
    trend = max(trend_weights, key=trend_weights.get)
    result = {
        "scope": {"type": "overview", "id": str(enrollment.id), "title": "Mastery"},
        "state": "known",
        "mastery_score": float(score.quantize(Decimal("0.0001"))),
        "mastery_percent": int((score * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "confidence": _confidence(distinct, policy),
        "distinct_evidence_count": distinct,
        "effective_evidence": float(effective.quantize(Decimal("0.0001"))),
        "trend": trend,
        "policy_version": policy.version,
    }
    candidates = list(MasteryAggregate.objects.filter(
        user=user,
        study_enrollment=enrollment,
        scope_type__in=(MasteryScopeType.UNIT, MasteryScopeType.LESSON),
        weakness_status="actionable",
    ).order_by("mastery_score", "-distinct_evidence_count", "scope_type", "scope_id"))
    top = candidates[0] if candidates else None
    if top:
        model = Unit if top.scope_type == MasteryScopeType.UNIT else Lesson
        obj = model.objects.filter(id=top.scope_id).first()
        result["top_weakness"] = serialize_mastery(top, title=getattr(obj, "title", top.scope_id))
    else:
        result["top_weakness"] = None
    return result


def top_actionable_weaknesses(*, user, enrollment, limit=5):
    """Bounded AR-08 provider for cross-subject analytics; never client-ranked."""
    rows = list(
        MasteryAggregate.objects.filter(
            user=user,
            study_enrollment=enrollment,
            scope_type__in=(
                MasteryScopeType.SUBJECT,
                MasteryScopeType.UNIT,
                MasteryScopeType.LESSON,
            ),
            weakness_status="actionable",
        ).order_by(
            "mastery_score", "-effective_evidence", "scope_type", "scope_id"
        )[:limit]
    )
    subject_ids = [row.scope_id for row in rows if row.scope_type == MasteryScopeType.SUBJECT]
    unit_ids = [row.scope_id for row in rows if row.scope_type == MasteryScopeType.UNIT]
    lesson_ids = [row.scope_id for row in rows if row.scope_type == MasteryScopeType.LESSON]
    subjects = {
        str(row.id): row
        for row in Subject.objects.filter(id__in=subject_ids)
    }
    units = {
        str(row.id): row
        for row in Unit.objects.select_related("subject").filter(id__in=unit_ids)
    }
    lessons = {
        str(row.id): row
        for row in Lesson.objects.select_related("unit__subject").filter(id__in=lesson_ids)
    }
    result = []
    for row in rows:
        if row.scope_type == MasteryScopeType.SUBJECT:
            obj = subjects.get(row.scope_id)
            if obj is None:
                continue
            subject_id, unit_id, lesson_id = str(obj.id), None, None
            label = obj.name_ar
        elif row.scope_type == MasteryScopeType.UNIT:
            obj = units.get(row.scope_id)
            if obj is None:
                continue
            subject_id, unit_id, lesson_id = str(obj.subject_id), str(obj.id), None
            label = obj.title
        else:
            obj = lessons.get(row.scope_id)
            if obj is None:
                continue
            subject_id = str(obj.unit.subject_id)
            unit_id, lesson_id = str(obj.unit_id), str(obj.id)
            label = obj.title
        score = float(row.mastery_score)
        result.append({
            "scope": {
                "subject_id": subject_id,
                "unit_id": unit_id,
                "lesson_id": lesson_id,
            },
            "scope_type": row.scope_type,
            "scope_id": row.scope_id,
            "dimension": row.scope_type,
            "value": row.scope_id,
            "label": label,
            "mastery_score": score,
            "performance_ratio": score,
            "performance_percentage": round(score * 100, 2),
            "confidence": row.confidence,
            "evidence_count": row.distinct_evidence_count,
            "effective_evidence": float(row.effective_evidence),
            "trend": row.trend,
            "priority": row.weakness_priority,
            "reason": row.weakness_reason,
            "weakness_status": row.weakness_status,
            "policy_version": row.policy_version,
        })
    return result


def mastery_weakness_signals(*, user, enrollment, subject, unit=None, lesson=None):
    policy = get_mastery_policy()
    aggregates = MasteryAggregate.objects.filter(
        user=user, study_enrollment=enrollment, weakness_status="actionable",
    )
    scope_ids = {
        MasteryScopeType.SUBJECT: set() if (unit or lesson) else {str(subject.id)},
        MasteryScopeType.UNIT: set(),
        MasteryScopeType.LESSON: set(),
    }
    if lesson is not None:
        scope_ids[MasteryScopeType.LESSON].add(str(lesson.id))
    elif unit is not None:
        scope_ids[MasteryScopeType.UNIT].add(str(unit.id))
        scope_ids[MasteryScopeType.LESSON].update(
            str(value) for value in Lesson.objects.filter(unit=unit).values_list("id", flat=True)
        )
    else:
        unit_ids = list(Unit.objects.filter(subject=subject).values_list("id", flat=True))
        scope_ids[MasteryScopeType.UNIT].update(str(value) for value in unit_ids)
        scope_ids[MasteryScopeType.LESSON].update(
            str(value) for value in Lesson.objects.filter(unit_id__in=unit_ids).values_list("id", flat=True)
        )
    query = None
    from django.db.models import Q
    for scope_type, ids in scope_ids.items():
        clause = Q(scope_type=scope_type, scope_id__in=ids)
        query = clause if query is None else query | clause
    rows = list(aggregates.filter(query)) if query is not None else []
    unit_labels = dict(Unit.objects.filter(id__in=scope_ids[MasteryScopeType.UNIT]).values_list("id", "title"))
    lesson_labels = dict(Lesson.objects.filter(id__in=scope_ids[MasteryScopeType.LESSON]).values_list("id", "title"))
    labels = {MasteryScopeType.SUBJECT: {str(subject.id): subject.name_ar}, MasteryScopeType.UNIT: {str(k): v for k, v in unit_labels.items()}, MasteryScopeType.LESSON: {str(k): v for k, v in lesson_labels.items()}}
    signals = []
    for row in rows:
        signals.append(_aggregate_signal(row, labels[row.scope_type].get(row.scope_id, row.scope_id), subject, unit, lesson))
    selected_scope_type = "lesson" if lesson else "unit" if unit else "subject"
    selected_scope_id = str(lesson.id if lesson else unit.id if unit else subject.id)
    selected = MasteryAggregate.objects.filter(
        user=user, study_enrollment=enrollment, scope_type=selected_scope_type, scope_id=selected_scope_id,
    ).first()
    if selected:
        for dimension, field in (("difficulty", "difficulty_breakdown"), ("question_type", "question_type_breakdown"), ("source", "source_breakdown")):
            for value, item in getattr(selected, field).items():
                if item.get("weakness_status") != "actionable":
                    continue
                signals.append({
                    "scope": {"subject_id": str(subject.id), "unit_id": str(unit.id) if unit else None, "lesson_id": str(lesson.id) if lesson else None},
                    "scope_type": selected_scope_type,
                    "scope_id": selected_scope_id,
                    "dimension": dimension,
                    "value": str(value),
                    "label": str(value),
                    "mastery_score": item["mastery_score"],
                    "performance_ratio": item["mastery_score"],
                    "performance_percentage": item["mastery_percent"],
                    "confidence": item["confidence"],
                    "evidence_count": item["distinct_evidence_count"],
                    "effective_evidence": item["effective_evidence"],
                    "trend": "insufficient_data",
                    "priority": item.get("priority"),
                    "reason": item.get("reason"),
                    "weakness_status": "actionable",
                    "policy_version": policy.version,
                })
    signals.sort(key=lambda row: (row["mastery_score"], -row["effective_evidence"], row["dimension"], row["value"]))
    return {
        "scope": {"subject_id": str(subject.id), "unit_id": str(unit.id) if unit else None, "lesson_id": str(lesson.id) if lesson else None},
        "minimum_evidence": policy.weakness_min_distinct,
        "weakness_threshold": float(policy.weakness_max_score),
        "has_sufficient_evidence": bool(signals),
        "signals": signals,
        "policy_version": policy.version,
    }


def _aggregate_signal(row, label, subject, unit, lesson):
    score = float(row.mastery_score)
    return {
        "scope": {"subject_id": str(subject.id), "unit_id": str(unit.id) if unit else None, "lesson_id": str(lesson.id) if lesson else None},
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "dimension": row.scope_type,
        "value": row.scope_id,
        "label": label,
        "mastery_score": score,
        "performance_ratio": score,
        "performance_percentage": round(score * 100, 2),
        "confidence": row.confidence,
        "evidence_count": row.distinct_evidence_count,
        "effective_evidence": float(row.effective_evidence),
        "trend": row.trend,
        "priority": row.weakness_priority,
        "reason": row.weakness_reason,
        "weakness_status": row.weakness_status,
        "policy_version": row.policy_version,
    }
