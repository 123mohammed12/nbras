"""AR-05 Mock Exams built on the shared SelectionEngine and dynamic attempts."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Prefetch
from django.utils import timezone

from apps.assessments.models import (
    AssessmentBlueprint,
    AssessmentBlueprintVersion,
    AssessmentType,
)
from apps.attempts.models import AssessmentAttempt, AttemptStatus
from apps.attempts.services.custom_tests import create_custom_test
from apps.attempts.services.selection_engine import SelectionEngine, normalize_selection_spec
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, StudyEnrollment
from apps.ministerial_exams.models import MinisterialExamItem
from apps.question_bank.models import QuestionVersion, SourceType
from apps.subscriptions.models import GenerationMode


TERMINAL_STATUSES = (
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
    AttemptStatus.EXPIRED,
)
ACTIVE_STATUSES = (
    AttemptStatus.CREATED,
    AttemptStatus.IN_PROGRESS,
    AttemptStatus.PAUSED,
)


def _active_enrollment(user):
    enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
    if enrollment is None:
        raise ApplicationError("No active enrollment.", code="NO_ACTIVE_ENROLLMENT")
    return enrollment


def version_spec(version: AssessmentBlueprintVersion) -> dict:
    return {
        "subject_id": str(version.blueprint.subject_id),
        "scope": dict(version.scope or {"mode": "subject", "unit_ids": [], "lesson_ids": []}),
        "sources": list(version.source_types or []),
        "years": list(version.years or []),
        "difficulties": list((version.difficulty_distribution or {}).keys()),
        "question_types": list((version.question_type_distribution or {}).keys()),
        "count": version.question_count,
        "mode": "exam",
        "duration_minutes": version.duration_minutes,
        "exclude_previously_answered": False,
        "selection_buckets": list(version.selection_buckets or []),
    }


def _distribution(buckets, field):
    result = {}
    for bucket in buckets:
        key = str(bucket.get(field) or "")
        result[key] = result.get(key, 0) + int(bucket.get("count") or 0)
    return result


def blueprint_pool_readiness(version: AssessmentBlueprintVersion) -> dict:
    """Pool-only validation used by Admin/import before publication."""
    buckets = list(version.selection_buckets or [])
    policy_errors = []
    if sum(int(row.get("count") or 0) for row in buckets) != version.question_count:
        policy_errors.append("BUCKET_TOTAL_MISMATCH")
    expected = {
        "unit_id": {str(k): int(v) for k, v in (version.unit_distribution or {}).items()},
        "difficulty": {str(k): int(v) for k, v in (version.difficulty_distribution or {}).items()},
        "question_type": {str(k): int(v) for k, v in (version.question_type_distribution or {}).items()},
    }
    for field, distribution in expected.items():
        if _distribution(buckets, field) != distribution:
            policy_errors.append(f"{field.upper()}_DISTRIBUTION_MISMATCH")
    if not version.source_types or any(
        row.get("source") not in version.source_types for row in buckets
    ):
        policy_errors.append("SOURCE_POLICY_MISMATCH")
    if version.duration_minutes < 1 or version.total_points <= 0:
        policy_errors.append("INVALID_TIMING_OR_POINTS")

    subject_id = version.blueprint.subject_id
    counts = {}
    if SourceType.TRAINING in version.source_types:
        rows = QuestionVersion.objects.filter(
            question__subject_id=subject_id,
            question__source_type=SourceType.TRAINING,
            question__status=ContentStatus.PUBLISHED,
            status=ContentStatus.PUBLISHED,
            question__current_version_id=F("id"),
        ).values(
            "question__unit_id", "question__difficulty", "question__question_type",
        ).annotate(count=Count("id"))
        counts.update({
            (SourceType.TRAINING, str(row["question__unit_id"]), row["question__difficulty"], row["question__question_type"]): row["count"]
            for row in rows
        })
    if SourceType.MINISTERIAL in version.source_types:
        rows = MinisterialExamItem.objects.filter(
            question_version__question__subject_id=subject_id,
            question_version__question__source_type=SourceType.MINISTERIAL,
            question_version__question__status=ContentStatus.PUBLISHED,
            question_version__status=ContentStatus.PUBLISHED,
            question_version__question__current_version_id=F("question_version_id"),
            ministerial_exam__status=ContentStatus.PUBLISHED,
        )
        if version.years:
            rows = rows.filter(ministerial_exam__exam_year__in=version.years)
        rows = rows.values(
            "question_version__question__unit_id",
            "question_version__question__difficulty",
            "question_version__question__question_type",
        ).annotate(count=Count("id"))
        counts.update({
            (
                SourceType.MINISTERIAL,
                str(row["question_version__question__unit_id"]),
                row["question_version__question__difficulty"],
                row["question_version__question__question_type"],
            ): row["count"]
            for row in rows
        })

    bucket_rows = []
    for bucket in buckets:
        required = int(bucket.get("count") or 0)
        key = (
            bucket.get("source"), str(bucket.get("unit_id")),
            bucket.get("difficulty"), bucket.get("question_type"),
        )
        available = counts.get(key, 0)
        bucket_rows.append({**bucket, "required": required, "available": available})
    missing = [row for row in bucket_rows if row["available"] < row["required"]]
    return {
        "ready": not policy_errors and not missing,
        "required_total": version.question_count,
        "available_total": sum(min(row["required"], row["available"]) for row in bucket_rows),
        "missing_buckets": missing,
        "policy_errors": policy_errors,
        "bucket_availability": bucket_rows,
    }


@transaction.atomic
def publish_blueprint_version(version: AssessmentBlueprintVersion):
    readiness = blueprint_pool_readiness(version)
    if not readiness["ready"]:
        raise ApplicationError(
            "The Mock blueprint cannot be published because its pool is insufficient.",
            code="MOCK_BLUEPRINT_NOT_READY",
            fields=readiness,
        )
    AssessmentBlueprintVersion.objects.filter(
        blueprint=version.blueprint, is_current=True,
    ).exclude(id=version.id).update(is_current=False)
    version.status = ContentStatus.PUBLISHED
    version.is_current = True
    version.published_at = version.published_at or timezone.now()
    version.save(update_fields=["status", "is_current", "published_at"])
    blueprint = version.blueprint
    blueprint.status = ContentStatus.PUBLISHED
    blueprint.save(update_fields=["status"])
    return readiness


def _current_version(blueprint):
    prefetched = getattr(blueprint, "current_versions", None)
    version = prefetched[0] if prefetched else blueprint.versions.filter(
        is_current=True, status=ContentStatus.PUBLISHED,
    ).first()
    if version is None:
        raise ApplicationError(
            "The Mock blueprint has no published current version.",
            code="MOCK_BLUEPRINT_NOT_PUBLISHED",
        )
    return version


def _student_preview(*, user, enrollment, version):
    engine = SelectionEngine(
        user=user, enrollment=enrollment,
        spec=normalize_selection_spec(version_spec(version)),
        generation_mode=GenerationMode.MOCK,
    )
    return engine.preview()


def _require_student_readiness(*, user, enrollment, version):
    preview = _student_preview(user=user, enrollment=enrollment, version=version)
    if not preview["can_create_exact"]:
        raise ApplicationError(
            "لا توجد حالياً أسئلة جديدة كافية لإنشاء اختبار آخر بهذه الإعدادات.",
            code="QUESTION_POOL_EXHAUSTED",
        )
    return preview


def _card(
    blueprint,
    version,
    attempts,
    readiness,
    *,
    access_state="available",
    access_reason=None,
):
    active = next((item for item in attempts if item.status in ACTIVE_STATUSES), None)
    completed = next((item for item in attempts if item.status in TERMINAL_STATUSES), None)
    return {
        "id": str(blueprint.id),
        "key": blueprint.key,
        "title": version.title,
        "description": blueprint.description,
        "subject": {"id": str(blueprint.subject_id), "name": blueprint.subject.name_ar},
        "version": version.version_number,
        "question_count": version.question_count,
        "duration_minutes": version.duration_minutes,
        "total_points": float(version.total_points),
        "source_policy": list(version.source_types),
        "scope": version.scope,
        "unit_distribution": version.unit_distribution,
        "difficulty_distribution": version.difficulty_distribution,
        "question_type_distribution": version.question_type_distribution,
        "readiness": ({
            "ready": readiness["can_create_exact"],
            "reason_code": (
                None
                if readiness["can_create_exact"]
                else "QUESTION_POOL_EXHAUSTED"
            ),
        } if readiness is not None else None),
        "access_state": access_state,
        "access_reason": access_reason,
        "active_attempt_id": str(active.id) if active else None,
        "last_result": ({
            "attempt_id": str(completed.id),
            "percentage": float(completed.percentage),
            "score": float(completed.score),
            "maximum_score": float(completed.maximum_score),
        } if completed else None),
    }


def list_mock_blueprints(*, user, subject_id: str) -> list[dict]:
    enrollment = _active_enrollment(user)
    blueprints = list(AssessmentBlueprint.objects.filter(
        subject_id=subject_id,
        status=ContentStatus.PUBLISHED,
        versions__is_current=True,
        versions__status=ContentStatus.PUBLISHED,
    ).select_related("subject").prefetch_related(Prefetch(
        "versions",
        queryset=AssessmentBlueprintVersion.objects.filter(
            is_current=True, status=ContentStatus.PUBLISHED,
        ),
        to_attr="current_versions",
    )).distinct())
    attempts = list(AssessmentAttempt.objects.filter(
        user=user, blueprint__in=blueprints,
    ).order_by("-created_at"))
    result = []
    for blueprint in blueprints:
        version = _current_version(blueprint)
        own = [item for item in attempts if item.blueprint_id == blueprint.id]
        try:
            SelectionEngine(
                user=user, enrollment=enrollment,
                spec=normalize_selection_spec(version_spec(version)),
                generation_mode=GenerationMode.MOCK,
            )
            pool = blueprint_pool_readiness(version)
            readiness = {
                "can_create_exact": pool["ready"],
                "maximum_creatable": pool["available_total"],
                "missing_buckets": pool["missing_buckets"],
            }
            result.append(_card(blueprint, version, own, readiness))
        except ApplicationError as exc:
            # Listing is a discovery endpoint.  Any access denial belongs to
            # the individual blueprint card and must not fail the whole tab.
            # This includes exhausted free Mock allowances as well as regular
            # subscription/scope denials.
            if exc.status_code != 403:
                raise
            result.append(_card(
                blueprint,
                version,
                own,
                None,
                access_state="locked",
                access_reason=exc.code,
            ))
    return result


def get_mock_blueprint(*, user, blueprint_id: str) -> dict:
    enrollment = _active_enrollment(user)
    blueprint = AssessmentBlueprint.objects.filter(id=blueprint_id).select_related("subject").first()
    if blueprint is None:
        raise ApplicationError("Mock blueprint not found.", code="MOCK_BLUEPRINT_NOT_FOUND", status_code=404)
    if blueprint.status != ContentStatus.PUBLISHED:
        raise ApplicationError("Mock blueprint is not published.", code="MOCK_BLUEPRINT_NOT_PUBLISHED")
    version = _current_version(blueprint)
    readiness = _student_preview(user=user, enrollment=enrollment, version=version)
    attempts = list(AssessmentAttempt.objects.filter(
        user=user, blueprint=blueprint,
    ).order_by("-created_at"))
    return _card(blueprint, version, attempts, readiness)


@transaction.atomic
def start_mock(*, user, blueprint_id: str, idempotency_key: str | None = None, parent=None):
    if idempotency_key:
        existing = AssessmentAttempt.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if existing:
            if existing.dynamic_assessment_type != AssessmentType.MOCK_EXAM:
                raise ApplicationError("Idempotency key belongs to another attempt.", code="MOCK_ATTEMPT_INVALID", status_code=409)
            return existing
    enrollment = _active_enrollment(user)
    blueprint = AssessmentBlueprint.objects.select_for_update().filter(
        id=blueprint_id,
    ).select_related("subject").first()
    if blueprint is None:
        raise ApplicationError("Mock blueprint not found.", code="MOCK_BLUEPRINT_NOT_FOUND", status_code=404)
    if blueprint.status != ContentStatus.PUBLISHED:
        raise ApplicationError("Mock blueprint is not published.", code="MOCK_BLUEPRINT_NOT_PUBLISHED")
    version = _current_version(blueprint)
    _require_student_readiness(user=user, enrollment=enrollment, version=version)
    point_value = (version.total_points / Decimal(version.question_count)).quantize(Decimal("0.01"))
    if point_value * version.question_count != version.total_points:
        raise ApplicationError(
            "Mock points policy cannot be represented per question.",
            code="MOCK_BLUEPRINT_NOT_READY",
        )
    snapshot = {
        "blueprint_id": str(blueprint.id),
        "blueprint_key": blueprint.key,
        "blueprint_version": version.version_number,
        "title": version.title,
        "question_count": version.question_count,
        "duration_minutes": version.duration_minutes,
        "total_points": str(version.total_points),
        "source_types": version.source_types,
        "scope": version.scope,
        "unit_distribution": version.unit_distribution,
        "difficulty_distribution": version.difficulty_distribution,
        "question_type_distribution": version.question_type_distribution,
        "selection_buckets": version.selection_buckets,
        "selection_policy_version": version.selection_policy_version,
    }
    return create_custom_test(
        user=user,
        payload=version_spec(version),
        idempotency_key=idempotency_key,
        parent_attempt=parent,
        dynamic_assessment_type=AssessmentType.MOCK_EXAM,
        dynamic_title=version.title,
        blueprint=blueprint,
        source_scope_extra={"blueprint_version": version.version_number},
        selection_policy_extra={"blueprint_snapshot": snapshot},
        points_per_question=point_value,
    )


def new_mock_from_attempt(*, user, parent, idempotency_key=None):
    if parent.dynamic_assessment_type != AssessmentType.MOCK_EXAM or not parent.blueprint_id:
        raise ApplicationError("The source Mock attempt is invalid.", code="MOCK_ATTEMPT_INVALID")
    return start_mock(
        user=user, blueprint_id=str(parent.blueprint_id),
        idempotency_key=idempotency_key, parent=parent,
    )
