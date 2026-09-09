from decimal import Decimal
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.core.exceptions import ValidationError
from apps.ministerial_exams.models import (
    LessonMinisterialBatch,
    LessonMinisterialBatchItem,
    MinisterialExam,
    MinisterialExamItem,
)


@transaction.atomic
def recalculate_exam_totals(exam: MinisterialExam) -> MinisterialExam:
    """
    Recalculates total_questions and total_points for a MinisterialExam
    based on its actual MinisterialExamItem rows.
    """
    locked_exam = MinisterialExam.objects.select_for_update().get(id=exam.id)
    items = MinisterialExamItem.objects.filter(ministerial_exam=locked_exam)

    item_count = items.count()
    total_pts = sum((item.points for item in items if item.points), Decimal("0.00"))

    locked_exam.total_questions = item_count
    locked_exam.total_points = Decimal(str(total_pts))
    locked_exam.save(update_fields=["total_questions", "total_points", "updated_at"])

    return locked_exam


def validate_ministerial_exam_publishability(exam: MinisterialExam):
    """
    Validates that a MinisterialExam is structurally complete and ready for publishing.
    """
    items_count = exam.items.count()
    if items_count == 0:
        raise ValidationError("لا يمكن نشر نموذج وزاري لا يحتوي على أسئلة (Items).")

    # Check that each item has a valid QuestionVersion and options order
    for item in exam.items.all():
        if not item.question_version:
            raise ValidationError(f"العنصر رقم {item.question_number} يفتقر إلى نسخة سؤال صالحة.")
        if item.question_version.question.status != "published":
            raise ValidationError(f"السؤال رقم {item.question_number} غير منشور.")

    # Check for linked Assessment
    if not exam.assessment:
        from apps.assessments.models import Assessment, AssessmentType
        assessment = Assessment.objects.filter(
            subject=exam.subject,
            assessment_type=AssessmentType.MINISTERIAL_EXAM,
            title__contains=exam.model_code,
        ).first()
        if not assessment:
            assessment = Assessment.objects.filter(
                subject=exam.subject,
                assessment_type=AssessmentType.MINISTERIAL_EXAM,
                title__contains=exam.title,
            ).first()
        if assessment:
            exam.assessment = assessment
            exam.save(update_fields=["assessment"])

    if not exam.assessment:
        raise ValidationError("النموذج الوزاري غير مرتبط باختبار تفاعلي (Assessment).")


def lesson_ministerial_batch_sizes(total: int, target: int = 20) -> list[int]:
    """Create the approved initial layout while avoiding a tiny tail."""
    if total <= 0:
        return []
    target = max(1, target)
    if total <= target:
        return [total]
    full, remainder = divmod(total, target)
    if remainder == 0:
        return [target] * full
    batch_count = full + 1
    if batch_count <= 3:
        kept_full = 1
    elif remainder < max(2, (target + 1) // 2):
        kept_full = full - 1
    else:
        kept_full = full
    tail_count = batch_count - kept_full
    tail_total = total - (kept_full * target)
    base, extra = divmod(tail_total, tail_count)
    tail = [base + (1 if index < extra else 0) for index in range(tail_count)]
    return ([target] * kept_full) + tail


def balanced_part_sizes(total: int, maximum: int) -> list[int]:
    """Split only oversized model subsets into balanced bounded parts."""
    if total <= 0:
        return []
    maximum = max(1, maximum)
    if total <= maximum:
        return [total]
    part_count = (total + maximum - 1) // maximum
    base, extra = divmod(total, part_count)
    return [base + (1 if index < extra else 0) for index in range(part_count)]


def _mixed_year_order(items):
    buckets = defaultdict(list)
    for item in items:
        buckets[item.ministerial_exam.exam_year].append(item)
    years = sorted(buckets, reverse=True)
    ordered = []
    while years:
        remaining_years = []
        for year in years:
            bucket = buckets[year]
            ordered.append(bucket.pop(0))
            if bucket:
                remaining_years.append(year)
        years = remaining_years
    return ordered


def _attempt_occurrence_id(attempt_question):
    if attempt_question.ministerial_exam_item_id:
        return str(attempt_question.ministerial_exam_item_id)
    if attempt_question.assessment_item_id:
        value = attempt_question.assessment_item.ministerial_exam_item_id
        if value:
            return str(value)
    return (attempt_question.source_metadata_snapshot or {}).get(
        "ministerial_exam_item_id"
    )


@transaction.atomic
def sync_lesson_ministerial_batches(lesson) -> list[LessonMinisterialBatch]:
    """Publish stable batches and append future occurrences to later batches."""
    from apps.attempts.models import AssessmentAttempt, AttemptQuestion
    from apps.curriculum.models import ContentStatus, Lesson

    lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
    target = max(
        1, getattr(settings, "ASSESSMENT_LESSON_MINISTERIAL_TARGET_SIZE", 20)
    )
    eligible = list(
        MinisterialExamItem.objects.filter(
            question_version__question__lesson=lesson,
            question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam__status=ContentStatus.PUBLISHED,
        )
        .select_related("ministerial_exam")
        .order_by(
            "-ministerial_exam__exam_year",
            "ministerial_exam__exam_role",
            "ministerial_exam__model_number",
            "sort_order",
            "id",
        )
    )
    eligible_by_id = {str(item.id): item for item in eligible}
    batches = list(
        LessonMinisterialBatch.objects.select_for_update()
        .filter(lesson=lesson)
        .order_by("batch_index")
    )
    assigned = set(
        LessonMinisterialBatchItem.objects.filter(batch__lesson=lesson).values_list(
            "ministerial_exam_item_id", flat=True
        )
    )
    assigned_text = {str(value) for value in assigned}

    # AR-01R2 had logical batch scopes but no persistent identity. Preserve the
    # newest frozen set for every already-used batch when seeding AR-02.
    if not batches:
        latest_by_index = {}
        prior_attempts = AssessmentAttempt.objects.filter(
            source_scope__kind="lesson_ministerial",
            source_scope__source_id=str(lesson.id),
        ).order_by("-created_at")
        for attempt in prior_attempts:
            raw_index = (attempt.source_scope or {}).get("batch")
            if isinstance(raw_index, int) and raw_index > 0:
                latest_by_index.setdefault(raw_index, attempt)
        for batch_index in sorted(latest_by_index):
            batch = LessonMinisterialBatch.objects.create(
                lesson=lesson, batch_index=batch_index, target_size=target
            )
            questions = AttemptQuestion.objects.filter(
                attempt=latest_by_index[batch_index]
            ).select_related("assessment_item").order_by("sort_order")
            rows = []
            for question in questions:
                occurrence_id = _attempt_occurrence_id(question)
                if (
                    occurrence_id in eligible_by_id
                    and occurrence_id not in assigned_text
                ):
                    rows.append(
                        LessonMinisterialBatchItem(
                            batch=batch,
                            ministerial_exam_item=eligible_by_id[occurrence_id],
                            sort_order=len(rows) + 1,
                        )
                    )
                    assigned.add(eligible_by_id[occurrence_id].id)
                    assigned_text.add(occurrence_id)
            if rows:
                LessonMinisterialBatchItem.objects.bulk_create(rows)
                batches.append(batch)
            else:
                batch.delete()

    remaining = [item for item in eligible if item.id not in assigned]
    if remaining:
        next_index = max((batch.batch_index for batch in batches), default=0) + 1
        ordered = _mixed_year_order(remaining)
        for size in lesson_ministerial_batch_sizes(len(ordered), target):
            batch = LessonMinisterialBatch.objects.create(
                lesson=lesson, batch_index=next_index, target_size=target
            )
            selected, ordered = ordered[:size], ordered[size:]
            LessonMinisterialBatchItem.objects.bulk_create(
                [
                    LessonMinisterialBatchItem(
                        batch=batch,
                        ministerial_exam_item=item,
                        sort_order=index,
                    )
                    for index, item in enumerate(selected, 1)
                ]
            )
            batches.append(batch)
            next_index += 1
    return sorted(batches, key=lambda item: item.batch_index)


def ministerial_coverage_count(*, user, enrollment, lesson_id=None, unit_id=None, subject_id=None):
    """Count distinct finalized historical occurrences, never starts/practice."""
    from apps.attempts.models import AttemptQuestion, AttemptStatus, AttemptType

    query = AttemptQuestion.objects.filter(
        attempt__user=user,
        attempt__study_enrollment=enrollment,
        attempt__status__in=[
            AttemptStatus.SUBMITTED,
            AttemptStatus.EVALUATED,
            AttemptStatus.PENDING_REVIEW,
        ],
        attempt__attempt_type__in=[AttemptType.NORMAL, AttemptType.RETRY_FULL],
        source_type="ministerial",
    ).exclude(attempt__dynamic_assessment_type__in=["wrong_answers_test", "weakness_practice"])
    if lesson_id is not None:
        query = query.filter(question_version__question__lesson_id=lesson_id)
    if unit_id is not None:
        query = query.filter(question_version__question__unit_id=unit_id)
    if subject_id is not None:
        query = query.filter(question_version__question__subject_id=subject_id)
    occurrences = set()
    for direct_id, linked_id, snapshot_id in query.values_list(
        "ministerial_exam_item_id",
        "assessment_item__ministerial_exam_item_id",
        "source_metadata_snapshot__ministerial_exam_item_id",
    ).distinct():
        value = direct_id or linked_id or snapshot_id
        if value:
            occurrences.add(str(value))
    return len(occurrences)
