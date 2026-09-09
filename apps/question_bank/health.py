from __future__ import annotations

from django.db.models import Count, F, Q

from apps.assessments.models import AssessmentBlueprintVersion, TrainingBatch
from apps.attempts.services.mock_exams import blueprint_pool_readiness
from apps.curriculum.models import ContentStatus
from apps.question_bank.models import Question, SourceType


def pool_health(*, subject_id=None, row_limit=2000):
    """Aggregated current eligible pool counts; never loads question rows."""
    query = Question.objects.filter(
        status=ContentStatus.PUBLISHED,
        current_version__status=ContentStatus.PUBLISHED,
        current_version__is_current=True,
    )
    if subject_id:
        query = query.filter(subject_id=subject_id)
    rows = list(
        query.values(
            "subject_id", "subject__name_ar",
            "unit_id", "unit__title", "lesson_id", "lesson__title",
            "source_type", "difficulty", "question_type",
        )
        .annotate(count=Count("id"))
        .order_by("subject_id", "unit_id", "lesson_id", "source_type", "difficulty", "question_type")[:row_limit]
    )
    return {
        "subject_id": subject_id,
        "eligible_total": sum(row["count"] for row in rows),
        "rows": rows,
        "truncated": len(rows) == row_limit,
    }


def training_batch_health(*, subject_id=None, limit=500):
    query = TrainingBatch.objects.all()
    if subject_id:
        query = query.filter(subject_id=subject_id)
    batches = list(
        query.select_related("subject", "unit", "lesson")
        .annotate(
            item_count=Count("items", distinct=True),
            eligible_item_count=Count(
                "items",
                filter=Q(
                    items__question_version__status=ContentStatus.PUBLISHED,
                    items__question_version__question__status=ContentStatus.PUBLISHED,
                    items__question_version__question__source_type=SourceType.TRAINING,
                    items__question_version__question__current_version_id=F("items__question_version_id"),
                ),
                distinct=True,
            ),
            retired_item_count=Count(
                "items",
                filter=~Q(items__question_version__question__status=ContentStatus.PUBLISHED),
                distinct=True,
            ),
            non_current_item_count=Count(
                "items",
                filter=~Q(items__question_version__question__current_version_id=F("items__question_version_id")),
                distinct=True,
            ),
        )
        .order_by("subject_id", "scope_key", "batch_index")[:limit]
    )
    rows = []
    for batch in batches:
        scope_consistent = (
            (batch.scope_type == "lesson" and batch.lesson_id and batch.unit_id)
            or (batch.scope_type == "unit" and batch.unit_id and not batch.lesson_id)
            or (batch.scope_type == "subject" and not batch.unit_id and not batch.lesson_id)
        )
        rows.append({
            "id": str(batch.pk),
            "scope_key": batch.scope_key,
            "batch_index": batch.batch_index,
            "item_count": batch.item_count,
            "eligible_item_count": batch.eligible_item_count,
            "retired_item_count": batch.retired_item_count,
            "non_current_item_count": batch.non_current_item_count,
            "empty": batch.item_count == 0,
            "scope_consistent": bool(scope_consistent),
        })
    return {
        "batch_count": len(rows),
        "empty_or_broken": sum(row["empty"] or not row["scope_consistent"] for row in rows),
        "impacted_by_retirement_or_versioning": sum(
            bool(row["retired_item_count"] or row["non_current_item_count"]) for row in rows
        ),
        "rows": rows,
        "truncated": len(rows) == limit,
    }


def mock_blueprint_health(*, subject_id=None, limit=100):
    query = AssessmentBlueprintVersion.objects.filter(
        is_current=True, status=ContentStatus.PUBLISHED,
    ).select_related("blueprint", "blueprint__subject")
    if subject_id:
        query = query.filter(blueprint__subject_id=subject_id)
    rows = []
    for version in query.order_by("blueprint__subject_id", "blueprint_id")[:limit]:
        readiness = blueprint_pool_readiness(version)
        rows.append({
            "blueprint_id": str(version.blueprint_id),
            "title": str(version.blueprint),
            "version": version.version_number,
            "ready": readiness["ready"],
            "missing_buckets": readiness["missing_buckets"],
            "policy_errors": readiness["policy_errors"],
        })
    return {"rows": rows, "truncated": len(rows) == limit}
