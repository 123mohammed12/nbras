from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q, Subquery

from apps.assessments.models import (
    Assessment,
    AssessmentType,
    TrainingBatch,
    TrainingBatchItem,
    TrainingBatchScope,
)
from apps.attempts.models import (
    AssessmentAttempt,
    AttemptQuestion,
    AttemptStatus,
    AttemptType,
)
from apps.curriculum.models import ContentStatus, Lesson, Subject, Unit
from apps.ministerial_exams.services import lesson_ministerial_batch_sizes
from apps.question_bank.models import QuestionVersion, SourceType
from apps.entitlements.services.access_service import check_resources_access_batch


TERMINAL_ATTEMPT_STATUSES = {
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
    AttemptStatus.EXPIRED,
    AttemptStatus.CANCELLED,
}


def training_scope_key(scope_type: str, source_id) -> str:
    if scope_type not in TrainingBatchScope.values:
        raise ValueError(f"Unsupported Training scope: {scope_type}")
    return f"{scope_type}:{source_id}"


def training_source_kind(scope_type: str) -> str:
    return f"{scope_type}_training"


def training_source_scope(scope_type: str, source_id, batch_index: int) -> dict:
    return {
        "kind": training_source_kind(scope_type),
        "source_id": str(source_id),
        "batch": int(batch_index),
    }


def _round_robin(groups):
    buckets = [list(values) for _, values in sorted(groups.items(), key=lambda row: str(row[0]))]
    result = []
    while buckets:
        remaining = []
        for bucket in buckets:
            result.append(bucket.pop(0))
            if bucket:
                remaining.append(bucket)
        buckets = remaining
    return result


def _difficulty_type_order(versions):
    grouped = defaultdict(list)
    for version in versions:
        question = version.question
        grouped[(question.difficulty, question.question_type)].append(version)
    for values in grouped.values():
        values.sort(key=lambda item: str(item.question_id))
    return _round_robin(grouped)


def _balanced_training_order(versions, scope_type):
    if scope_type == TrainingBatchScope.LESSON:
        return _difficulty_type_order(versions)
    if scope_type == TrainingBatchScope.UNIT:
        by_lesson = defaultdict(list)
        for version in versions:
            by_lesson[str(version.question.lesson_id or "")].append(version)
        for key, values in list(by_lesson.items()):
            by_lesson[key] = _difficulty_type_order(values)
        return _round_robin(by_lesson)

    by_unit = defaultdict(list)
    for version in versions:
        by_unit[str(version.question.unit_id or "")].append(version)
    for unit_id, unit_values in list(by_unit.items()):
        by_lesson = defaultdict(list)
        for version in unit_values:
            by_lesson[str(version.question.lesson_id or "")].append(version)
        for key, values in list(by_lesson.items()):
            by_lesson[key] = _difficulty_type_order(values)
        by_unit[unit_id] = _round_robin(by_lesson)
    return _round_robin(by_unit)


def _distribute_across_batches(versions, scope_type, sizes):
    """Spread curriculum axes across every initial batch before local ordering."""
    if len(sizes) <= 1 or scope_type == TrainingBatchScope.LESSON:
        ordered = _balanced_training_order(versions, scope_type)
        result = []
        for size in sizes:
            selected, ordered = ordered[:size], ordered[size:]
            result.append(selected)
        return result
    groups = defaultdict(list)
    for version in versions:
        question = version.question
        key = (
            str(question.lesson_id or "")
            if scope_type == TrainingBatchScope.UNIT
            else str(question.unit_id or "")
        )
        groups[key].append(version)
    batches = [[] for _ in sizes]
    cursor = 0
    for _, group in sorted(groups.items(), key=lambda row: (len(row[1]), str(row[0]))):
        group = _balanced_training_order(group, TrainingBatchScope.LESSON)
        for version in group:
            for _ in range(len(batches)):
                index = cursor % len(batches)
                cursor += 1
                if len(batches[index]) < sizes[index]:
                    batches[index].append(version)
                    break
    return [_balanced_training_order(batch, scope_type) for batch in batches]


def _locked_scope(scope_type, source_id):
    if scope_type == TrainingBatchScope.LESSON:
        return Lesson.objects.select_for_update().select_related("unit__subject").get(
            id=source_id, status=ContentStatus.PUBLISHED
        )
    if scope_type == TrainingBatchScope.UNIT:
        return Unit.objects.select_for_update().select_related("subject").get(
            id=source_id, status=ContentStatus.PUBLISHED
        )
    return Subject.objects.select_for_update().get(
        id=source_id, status=ContentStatus.PUBLISHED
    )


def _scope_parents(scope_type, scope):
    if scope_type == TrainingBatchScope.LESSON:
        return scope.unit.subject, scope.unit, scope
    if scope_type == TrainingBatchScope.UNIT:
        return scope.subject, scope, None
    return scope, None, None


def _eligible_versions_queryset(scope_type, source_id):
    filters = {
        "question__source_type": SourceType.TRAINING,
        "question__status": ContentStatus.PUBLISHED,
        "status": ContentStatus.PUBLISHED,
        "question__current_version_id": F("id"),
    }
    if scope_type == TrainingBatchScope.LESSON:
        filters["question__lesson_id"] = source_id
    elif scope_type == TrainingBatchScope.UNIT:
        filters["question__unit_id"] = source_id
    else:
        filters["question__subject_id"] = source_id
    return (
        QuestionVersion.objects.filter(**filters)
        .select_related("question")
        .order_by("question__created_at", "question_id")
    )


@transaction.atomic
def sync_training_batches(scope_type: str, source_id) -> list[TrainingBatch]:
    """Create stable batches once and append future logical questions later."""
    scope = _locked_scope(scope_type, source_id)
    subject, unit, lesson = _scope_parents(scope_type, scope)
    scope_key = training_scope_key(scope_type, source_id)
    target = max(1, getattr(settings, "ASSESSMENT_TRAINING_TARGET_SIZE", 20))
    batches = list(
        TrainingBatch.objects.select_for_update()
        .filter(scope_key=scope_key)
        .order_by("batch_index")
    )
    assigned_question_ids = TrainingBatchItem.objects.filter(
        batch__scope_key=scope_key
    ).values("question_version__question_id")
    sync_limit = max(
        target,
        getattr(settings, "ASSESSMENT_TRAINING_SYNC_LIMIT", 500),
    )
    new_versions = list(
        _eligible_versions_queryset(scope_type, source_id)
        .exclude(question_id__in=Subquery(assigned_question_ids))[:sync_limit]
    )
    if not new_versions:
        return batches

    sizes = lesson_ministerial_batch_sizes(len(new_versions), target)
    selections = _distribute_across_batches(new_versions, scope_type, sizes)
    next_index = max((batch.batch_index for batch in batches), default=0) + 1
    for selected in selections:
        batch = TrainingBatch.objects.create(
            scope_type=scope_type,
            scope_key=scope_key,
            subject=subject,
            unit=unit,
            lesson=lesson,
            batch_index=next_index,
            free_access_rank=next_index,
            target_size=target,
        )
        TrainingBatchItem.objects.bulk_create(
            [
                TrainingBatchItem(
                    batch=batch,
                    question_version=version,
                    sort_order=index,
                    source_metadata=dict(version.question.metadata or {}),
                )
                for index, version in enumerate(selected, 1)
            ]
        )
        batches.append(batch)
        next_index += 1
    return batches


def eligible_training_question_count(*, scope_type: str, source_id) -> int:
    return _eligible_versions_queryset(scope_type, source_id).count()


def training_coverage_count(*, user, enrollment, scope_type: str, source_id) -> int:
    query = AttemptQuestion.objects.filter(
        attempt__user=user,
        attempt__study_enrollment=enrollment,
        attempt__status__in=[
            AttemptStatus.SUBMITTED,
            AttemptStatus.EVALUATED,
            AttemptStatus.PENDING_REVIEW,
        ],
        attempt__attempt_type__in=[AttemptType.NORMAL, AttemptType.RETRY_FULL],
        source_type=SourceType.TRAINING,
    ).exclude(attempt__dynamic_assessment_type__in=["wrong_answers_test", "weakness_practice"])
    if scope_type == TrainingBatchScope.LESSON:
        query = query.filter(question_version__question__lesson_id=source_id)
    elif scope_type == TrainingBatchScope.UNIT:
        query = query.filter(question_version__question__unit_id=source_id)
    else:
        query = query.filter(question_version__question__subject_id=source_id)
    return query.values("question_version__question_id").distinct().count()


def training_batch_item_ids(*, scope_type: str, source_id, batch_index: int):
    batch = TrainingBatch.objects.filter(
        scope_key=training_scope_key(scope_type, source_id),
        batch_index=batch_index,
    ).first()
    if batch is None:
        return []
    return [
        str(value)
        for value in batch.items.filter(
            question_version__question__source_type=SourceType.TRAINING,
            question_version__question__status=ContentStatus.PUBLISHED,
            question_version__status=ContentStatus.PUBLISHED,
            question_version__question__current_version_id=F("question_version_id"),
        )
        .order_by("sort_order")
        .values_list("question_version_id", flat=True)
    ]


def dynamic_training_assessment(scope_type: str, source_id):
    marker = f"dynamic-source:{training_source_kind(scope_type)}"
    filters = {
        "assessment_type": AssessmentType.TRAINING_TEST,
        "description": marker,
        "status": ContentStatus.PUBLISHED,
    }
    if scope_type == TrainingBatchScope.LESSON:
        filters["lesson_id"] = source_id
    elif scope_type == TrainingBatchScope.UNIT:
        filters.update(unit_id=source_id, lesson__isnull=True)
    else:
        filters.update(subject_id=source_id, unit__isnull=True, lesson__isnull=True)
    return Assessment.objects.filter(**filters).first()


def training_batch_cards(
    *, user, enrollment, scope_type: str, source_id, limit=None, offset=0,
    prioritize=True,
):
    sync_training_batches(scope_type, source_id)
    batches = list(
        TrainingBatch.objects.filter(scope_key=training_scope_key(scope_type, source_id))
        .annotate(
            eligible_item_count=Count(
                "items",
                filter=Q(
                    items__question_version__question__source_type=SourceType.TRAINING,
                    items__question_version__question__status=ContentStatus.PUBLISHED,
                    items__question_version__status=ContentStatus.PUBLISHED,
                    items__question_version__question__current_version_id=F("items__question_version_id"),
                ),
            )
        )
        .order_by("batch_index")
    )
    assessment = dynamic_training_assessment(scope_type, source_id)
    batch_count = len(batches)
    attempts = []
    if assessment is not None:
        attempts = list(
            AssessmentAttempt.objects.filter(
                user=user,
                study_enrollment=enrollment,
                assessment=assessment,
            )
            .annotate(actual_question_count=Count("attempt_questions"))
            .order_by("-created_at")
        )
    if limit is not None:
        if prioritize:
            attempted_indexes = {
                (item.source_scope or {}).get("batch")
                for item in attempts
                if (item.source_scope or {}).get("kind") == training_source_kind(scope_type)
                and str((item.source_scope or {}).get("source_id")) == str(source_id)
            }
            active_indexes = [
                (item.source_scope or {}).get("batch")
                for item in attempts
                if item.status not in TERMINAL_ATTEMPT_STATUSES
            ]
            recent_indexes = [
                (item.source_scope or {}).get("batch")
                for item in attempts
                if item.status in TERMINAL_ATTEMPT_STATUSES
            ]
            next_index = next(
                (batch.batch_index for batch in batches if batch.batch_index not in attempted_indexes),
                None,
            )
            preferred = [*active_indexes, next_index, *recent_indexes]
            selected_indexes = []
            for value in preferred:
                if value and value not in selected_indexes:
                    selected_indexes.append(value)
                if len(selected_indexes) == limit:
                    break
            for batch in batches:
                if batch.batch_index not in selected_indexes:
                    selected_indexes.append(batch.batch_index)
                if len(selected_indexes) == limit:
                    break
            by_index = {batch.batch_index: batch for batch in batches}
            batches = [by_index[index] for index in selected_indexes if index in by_index]
        else:
            batches = batches[offset : offset + limit]
    total = eligible_training_question_count(scope_type=scope_type, source_id=source_id)
    covered = training_coverage_count(
        user=user, enrollment=enrollment, scope_type=scope_type, source_id=source_id
    )
    cards = []
    access_by_batch = check_resources_access_batch(
        user=user, enrollment=enrollment,
        resources=[{"type": "training_batch", "id": str(item.id)} for item in batches],
    )
    for batch in batches:
        access = access_by_batch[("training_batch", str(batch.id))]
        scope = training_source_scope(scope_type, source_id, batch.batch_index)
        scoped_attempts = [item for item in attempts if item.source_scope == scope]
        latest = scoped_attempts[0] if scoped_attempts else None
        active = next(
            (
                item for item in scoped_attempts
                if item.status not in TERMINAL_ATTEMPT_STATUSES
                and item.actual_question_count > 0
            ),
            None,
        )
        completed = [item for item in scoped_attempts if item.status in TERMINAL_ATTEMPT_STATUSES]
        best = max(completed, key=lambda item: item.percentage, default=None)
        question_count = batch.eligible_item_count
        cards.append(
            {
                "assessment_id": str(assessment.id) if assessment else None,
                "source_kind": training_source_kind(scope_type),
                "source_id": str(source_id),
                "assessment_type": AssessmentType.TRAINING_TEST,
                "title": f"الاختبار التدريبي {batch.batch_index}",
                "questions_count": question_count,
                "session_question_count": question_count,
                "total_pool_question_count": total,
                "covered_questions_count": covered,
                "batch_index": batch.batch_index,
                "batch_count": batch_count,
                "duration": None,
                "attempt_status": latest.status if latest else "not_started",
                "unfinished_attempt_id": str(active.id) if active else None,
                "last_score": float(latest.percentage) if latest else None,
                "best_score": float(best.percentage) if best else None,
                "is_available": question_count > 0 and access.allowed,
                "access": access.to_dict(),
                "free_access_rank": batch.free_access_rank,
                "display_state": "current" if active else "recent" if latest else "available",
                "last_activity_at": latest.last_activity_at.isoformat() if latest else None,
            }
        )
    next_card = next((item for item in cards if item["attempt_status"] == "not_started"), None)
    if next_card is not None:
        next_card["display_state"] = "next"
    if limit is not None and prioritize:
        priority = {"current": 0, "next": 1, "recent": 2, "available": 3}
        cards = sorted(
            cards,
            key=lambda item: (
                priority[item["display_state"]],
                -(item["batch_index"] if item["display_state"] == "recent" else 0),
                item["batch_index"],
            ),
        )[:limit]
    return cards, total, covered, batch_count
