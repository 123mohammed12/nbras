from decimal import Decimal

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.conf import settings

from apps.assessments.models import (
    Assessment, AssessmentItem, AssessmentType, AssessmentVersion,
    FeedbackPolicy, ShufflePolicy, TimingMode, TrainingBatch, TrainingBatchScope,
)
from apps.assessments.services.training import (
    eligible_training_question_count,
    sync_training_batches,
    training_batch_item_ids,
    training_scope_key,
    training_source_scope,
)
from apps.attempts.models import AssessmentAttempt, AttemptStatus
from apps.attempts.services.attempt_service import start_assessment_attempt
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, Lesson, StudyEnrollment, Unit
from apps.entitlements.services.access_service import check_resource_access
from apps.ministerial_exams.models import (
    MinisterialExam,
    MinisterialExamItem,
)
from apps.ministerial_exams.services import (
    balanced_part_sizes,
    sync_lesson_ministerial_batches,
)


TERMINAL_STATUSES = {
    AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW, AttemptStatus.EXPIRED, AttemptStatus.CANCELLED,
}

_DYNAMIC_UNIT_MINISTERIAL_MARKER = "dynamic-source:unit_ministerial"
_TRAINING_SOURCE_SCOPES = {
    "lesson_training": TrainingBatchScope.LESSON,
    "unit_training": TrainingBatchScope.UNIT,
    "subject_training": TrainingBatchScope.SUBJECT,
}
_DYNAMIC_SOURCES = {"lesson_ministerial", "unit_ministerial", *_TRAINING_SOURCE_SCOPES}


def get_assessment_entry(
    *, user, source_kind: str, source_id: str, year: int | None = None,
    batch_index: int | None = None, exam_id: str | None = None,
    part_index: int | None = None,
) -> dict:
    enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
    if enrollment is None:
        raise ApplicationError("No active enrollment.", code="NO_ACTIVE_ENROLLMENT")
    assessment = _resolve_existing_assessment(source_kind, source_id)
    if source_kind in _DYNAMIC_SOURCES:
        resource_type, resource = _source_access_resource(source_kind, source_id, batch_index)
        if resource is None:
            raise ApplicationError("Assessment source was not found.", code="ASSESSMENT_NOT_FOUND")
        decision = check_resource_access(
            user=user, enrollment=enrollment,
            resource_type=resource_type, resource_id=str(resource.id),
        )
    else:
        if assessment is None:
            raise ApplicationError("Assessment source was not found.", code="ASSESSMENT_NOT_FOUND")
        decision = check_resource_access(
            user=user, enrollment=enrollment,
            resource_type="assessment", resource_id=str(assessment.id),
        )
    source = (
        _source_metadata(
            source_kind,
            source_id,
            assessment,
            year=year,
            batch_index=batch_index,
            exam_id=exam_id,
            part_index=part_index,
        )
        if decision.allowed
        else _locked_source_metadata(source_kind, source_id)
    )
    attempt_query = AssessmentAttempt.objects.none()
    if assessment is not None:
        attempt_query = AssessmentAttempt.objects.filter(
            user=user, study_enrollment=enrollment, assessment=assessment
        ).annotate(actual_question_count=Count("attempt_questions"))
        if source_kind == "lesson_ministerial":
            attempt_query = attempt_query.filter(
                source_scope=_lesson_scope(source_id, batch_index)
            )
        elif source_kind == "unit_ministerial":
            attempt_query = attempt_query.filter(
                source_scope=_unit_scope(source_id, exam_id, part_index)
            )
        elif source_kind in _TRAINING_SOURCE_SCOPES:
            attempt_query = attempt_query.filter(
                source_scope=training_source_scope(
                    _TRAINING_SOURCE_SCOPES[source_kind], source_id, batch_index or 1
                )
            )
    attempts = list(attempt_query.order_by("-created_at"))
    active = next(
        (
            attempt
            for attempt in attempts
            if attempt.status not in TERMINAL_STATUSES
            and attempt.actual_question_count > 0
        ),
        None,
    )
    completed = [a for a in attempts if a.status in TERMINAL_STATUSES]
    best = max(completed, key=lambda a: a.percentage, default=None)
    latest = attempts[0] if attempts else None
    version = _current_version(assessment)
    return {
        "contract_version": 1,
        "source": source,
        "title": source["title"],
        "questions_count": source["questions_count"],
        "access": decision.to_dict(),
        "configuration": {
            "feedback_policy": getattr(version, "feedback_policy", FeedbackPolicy.IMMEDIATE),
            "timing_mode": getattr(version, "timing_mode", TimingMode.NONE),
            "duration_seconds": _duration_seconds(version, assessment),
            "allowed_display_modes": _display_modes(version),
            "default_display_mode": _display_mode(getattr(version, "default_display_mode", "single")),
            "allowed_attempt_modes": getattr(version, "allowed_attempt_modes", None) or ["practice"],
        },
        "active_attempt_id": str(active.id) if active else None,
        "latest_attempt": _attempt_summary(latest),
        "best_attempt": _attempt_summary(best),
        "attempts_count": len(attempts),
        "actions": {
            "can_start": bool(decision.allowed and source["questions_count"] > 0),
            "can_continue": bool(active),
            "can_review": bool(latest and latest.status in TERMINAL_STATUSES),
            "can_retry": bool(
                decision.allowed and latest and latest.status in TERMINAL_STATUSES
            ),
        },
    }


def start_from_source(
    *, user, source_kind: str, source_id: str, year: int | None = None,
    batch_index: int | None = None, exam_id: str | None = None,
    part_index: int | None = None,
    idempotency_key=None,
):
    if source_kind in _DYNAMIC_SOURCES:
        _assert_dynamic_source_access(
            user=user, source_kind=source_kind, source_id=source_id,
            batch_index=batch_index,
        )
    assessment = _materialize_source(source_kind, source_id)
    selected_item_ids = None
    selected_ministerial_item_ids = None
    selected_question_version_ids = None
    source_scope = None
    preserve_question_order = False
    if source_kind == "lesson_ministerial":
        source_scope = _lesson_scope(source_id, batch_index)
        selected_ministerial_item_ids = _select_lesson_ministerial_items(
            lesson_id=source_id,
            batch_index=batch_index,
        )
    elif source_kind == "unit_ministerial":
        source_scope = _unit_scope(source_id, exam_id, part_index)
        selected_ministerial_item_ids = _select_unit_ministerial_items(
            unit_id=source_id,
            exam_id=exam_id,
            part_index=part_index,
        )
    elif source_kind in _TRAINING_SOURCE_SCOPES:
        scope_type = _TRAINING_SOURCE_SCOPES[source_kind]
        selected_batch = batch_index or 1
        source_scope = training_source_scope(scope_type, source_id, selected_batch)
        sync_training_batches(scope_type, source_id)
        selected_question_version_ids = training_batch_item_ids(
            scope_type=scope_type,
            source_id=source_id,
            batch_index=selected_batch,
        )
        if not selected_question_version_ids:
            raise ApplicationError(
                "The requested Training batch is not available.",
                code="INVALID_ASSESSMENT_BATCH",
            )
    version = _current_version(assessment)
    allowed_modes = getattr(version, "allowed_attempt_modes", None) or ["practice", "exam"]
    preferred_mode = (
        "practice"
        if assessment.assessment_type in {
            AssessmentType.LESSON_MINISTERIAL,
            AssessmentType.LESSON_TEST,
            AssessmentType.TRAINING_TEST,
            AssessmentType.SELF_PRACTICE,
        }
        else "exam"
    )
    mode = preferred_mode if preferred_mode in allowed_modes else allowed_modes[0]
    return start_assessment_attempt(
        user=user,
        assessment_id=str(assessment.id),
        mode=mode,
        idempotency_key=idempotency_key,
        selected_item_ids=selected_item_ids,
        selected_ministerial_item_ids=selected_ministerial_item_ids,
        selected_question_version_ids=selected_question_version_ids,
        source_scope=source_scope,
        preserve_question_order=preserve_question_order,
    )


def _resolve_existing_assessment(source_kind, source_id):
    if source_kind == "assessment":
        return Assessment.objects.filter(id=source_id, status=ContentStatus.PUBLISHED).first()
    if source_kind == "ministerial_exam":
        exam = MinisterialExam.objects.select_related("assessment").filter(
            id=source_id, status=ContentStatus.PUBLISHED
        ).first()
        return exam.assessment if exam else None
    if source_kind == "lesson_ministerial":
        return Assessment.objects.filter(
            lesson_id=source_id, assessment_type=AssessmentType.LESSON_MINISTERIAL,
            status=ContentStatus.PUBLISHED,
        ).first()
    if source_kind == "unit_ministerial":
        return Assessment.objects.filter(
            unit_id=source_id,
            lesson__isnull=True,
            assessment_type=AssessmentType.UNIT_TEST,
            description=_DYNAMIC_UNIT_MINISTERIAL_MARKER,
            status=ContentStatus.PUBLISHED,
        ).first()
    if source_kind in _TRAINING_SOURCE_SCOPES:
        scope_type = _TRAINING_SOURCE_SCOPES[source_kind]
        marker = f"dynamic-source:{source_kind}"
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
    raise ApplicationError("Unsupported assessment source.", code="INVALID_ASSESSMENT_SOURCE")


def _materialize_source(source_kind, source_id):
    existing = _resolve_existing_assessment(source_kind, source_id)
    if source_kind not in _DYNAMIC_SOURCES:
        if existing is None:
            raise ApplicationError("Assessment source was not found.", code="ASSESSMENT_NOT_FOUND")
        return existing
    if source_kind == "lesson_ministerial":
        return _materialize_lesson_ministerial(source_id)
    if source_kind == "unit_ministerial":
        return _materialize_unit_ministerial(source_id)
    return _materialize_training(_TRAINING_SOURCE_SCOPES[source_kind], source_id)


@transaction.atomic
def _materialize_training(scope_type, source_id):
    if scope_type == TrainingBatchScope.LESSON:
        source = Lesson.objects.select_related("unit__subject").filter(
            id=source_id, status=ContentStatus.PUBLISHED
        ).first()
        subject = source.unit.subject if source else None
        unit = source.unit if source else None
        lesson = source
        title = f"تدريب الدرس - {source.title}" if source else ""
    elif scope_type == TrainingBatchScope.UNIT:
        source = Unit.objects.select_related("subject").filter(
            id=source_id, status=ContentStatus.PUBLISHED
        ).first()
        subject = source.subject if source else None
        unit = source
        lesson = None
        title = f"تدريب الوحدة - {source.title}" if source else ""
    else:
        from apps.curriculum.models import Subject
        source = Subject.objects.filter(id=source_id, status=ContentStatus.PUBLISHED).first()
        subject = source
        unit = lesson = None
        title = f"تدريب المادة - {source.name_ar}" if source else ""
    if source is None:
        raise ApplicationError("Training source was not found.", code="ASSESSMENT_NOT_FOUND")
    if eligible_training_question_count(scope_type=scope_type, source_id=source_id) == 0:
        raise ApplicationError(
            "This scope has no published Training questions.",
            code="NO_ASSESSMENT_QUESTIONS",
        )
    marker = f"dynamic-source:{scope_type}_training"
    assessment = Assessment.objects.filter(
        subject=subject,
        unit=unit,
        lesson=lesson,
        assessment_type=AssessmentType.TRAINING_TEST,
        description=marker,
    ).first()
    if assessment is None:
        assessment = Assessment.objects.create(
            subject=subject,
            unit=unit,
            lesson=lesson,
            assessment_type=AssessmentType.TRAINING_TEST,
            title=title,
            description=marker,
            status=ContentStatus.PUBLISHED,
            published_at=timezone.now(),
        )
    _ensure_dynamic_version(assessment)
    return assessment


@transaction.atomic
def _materialize_lesson_ministerial(lesson_id):
    lesson = Lesson.objects.select_related("unit__subject").filter(
        id=lesson_id, status=ContentStatus.PUBLISHED
    ).first()
    if lesson is None:
        raise ApplicationError("Lesson was not found.", code="ASSESSMENT_NOT_FOUND")
    if not MinisterialExamItem.objects.filter(
            question_version__question__lesson=lesson,
            question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam__status=ContentStatus.PUBLISHED,
        ).exists():
        raise ApplicationError("This lesson has no published questions.", code="NO_ASSESSMENT_QUESTIONS")
    assessment, _ = Assessment.objects.get_or_create(
        lesson=lesson, assessment_type=AssessmentType.LESSON_MINISTERIAL,
        defaults={
            "subject": lesson.unit.subject, "unit": lesson.unit,
            "title": f"اختبار وزاري تفاعلي - {lesson.title}",
            "description": "جميع الأسئلة الوزارية المنشورة المرتبطة بالدرس.",
            "status": ContentStatus.PUBLISHED, "published_at": timezone.now(),
        },
    )
    _ensure_dynamic_version(assessment)
    return assessment


@transaction.atomic
def _materialize_unit_ministerial(unit_id):
    unit = Unit.objects.select_related("subject").filter(
        id=unit_id, status=ContentStatus.PUBLISHED,
    ).first()
    if unit is None:
        raise ApplicationError("Unit was not found.", code="ASSESSMENT_NOT_FOUND")
    if not MinisterialExamItem.objects.filter(
            question_version__question__unit=unit,
            question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam__status=ContentStatus.PUBLISHED,
        ).exists():
        raise ApplicationError(
            "This unit has no published ministerial questions.",
            code="NO_ASSESSMENT_QUESTIONS",
        )
    assessment = Assessment.objects.filter(
        unit=unit,
        lesson__isnull=True,
        assessment_type=AssessmentType.UNIT_TEST,
        description=_DYNAMIC_UNIT_MINISTERIAL_MARKER,
    ).first()
    if assessment is None:
        assessment = Assessment.objects.create(
            subject=unit.subject,
            unit=unit,
            assessment_type=AssessmentType.UNIT_TEST,
            title=f"وزاريات الوحدة - {unit.title}",
            description=_DYNAMIC_UNIT_MINISTERIAL_MARKER,
            status=ContentStatus.PUBLISHED,
            published_at=timezone.now(),
        )
    _ensure_dynamic_version(assessment)
    return assessment


def _ensure_dynamic_version(assessment):
    current = _current_version(assessment)
    if current is not None:
        changed = []
        if current.question_shuffle_policy != ShufflePolicy.ALWAYS:
            current.question_shuffle_policy = ShufflePolicy.ALWAYS
            changed.append("question_shuffle_policy")
        if current.option_shuffle_policy != ShufflePolicy.ALWAYS:
            current.option_shuffle_policy = ShufflePolicy.ALWAYS
            changed.append("option_shuffle_policy")
        if current.feedback_policy != FeedbackPolicy.IMMEDIATE:
            current.feedback_policy = FeedbackPolicy.IMMEDIATE
            changed.append("feedback_policy")
        if changed:
            current.save(update_fields=changed)
        return
    AssessmentVersion.objects.create(
        assessment=assessment,
        version_number=1,
        total_points=Decimal("0.00"),
        question_count=0,
        allowed_display_modes=["one_by_one", "continuous"],
        default_display_mode="one_by_one",
        allowed_attempt_modes=["practice"],
        question_shuffle_policy=ShufflePolicy.ALWAYS,
        option_shuffle_policy=ShufflePolicy.ALWAYS,
        feedback_policy=FeedbackPolicy.IMMEDIATE,
        timing_mode=TimingMode.NONE,
        is_current=True,
        published_at=timezone.now(),
    )


def _source_metadata(
    source_kind,
    source_id,
    assessment,
    *,
    year=None,
    batch_index=None,
    exam_id=None,
    part_index=None,
):
    if source_kind in _TRAINING_SOURCE_SCOPES:
        scope_type = _TRAINING_SOURCE_SCOPES[source_kind]
        batches = sync_training_batches(scope_type, source_id)
        selected_batch = batch_index or 1
        batch = next((item for item in batches if item.batch_index == selected_batch), None)
        if batch is None:
            raise ApplicationError(
                "The requested Training batch is not available.",
                code="INVALID_ASSESSMENT_BATCH",
            )
        count = batch.items.filter(
            question_version__question__source_type="training",
            question_version__question__status=ContentStatus.PUBLISHED,
        ).count()
        total = eligible_training_question_count(scope_type=scope_type, source_id=source_id)
        return {
            "kind": source_kind,
            "id": str(source_id),
            "assessment_id": str(assessment.id) if assessment else None,
            "assessment_type": AssessmentType.TRAINING_TEST,
            "title": f"الاختبار التدريبي {selected_batch}",
            "questions_count": count,
            "session_question_count": count,
            "total_pool_question_count": total,
            "batch_index": selected_batch,
            "batch_count": len(batches),
            "target_session_size": max(
                1, getattr(settings, "ASSESSMENT_TRAINING_TARGET_SIZE", 20)
            ),
        }
    if source_kind == "lesson_ministerial":
        lesson = Lesson.objects.filter(id=source_id).first()
        if lesson is None:
            raise ApplicationError(
                "Lesson was not found.", code="ASSESSMENT_NOT_FOUND"
            )
        batches = sync_lesson_ministerial_batches(lesson)
        target = max(
            1,
            getattr(settings, "ASSESSMENT_LESSON_MINISTERIAL_TARGET_SIZE", 20),
        )
        selected_batch = batch_index or 1
        batch = next(
            (item for item in batches if item.batch_index == selected_batch), None
        )
        if batch is None:
            raise ApplicationError(
                "The requested lesson batch is not available.",
                code="INVALID_ASSESSMENT_BATCH",
            )
        eligible_filter = {
            "ministerial_exam_item__question_version__question__status": ContentStatus.PUBLISHED,
            "ministerial_exam_item__ministerial_exam__status": ContentStatus.PUBLISHED,
        }
        session_count = batch.batch_items.filter(**eligible_filter).count()
        total_count = MinisterialExamItem.objects.filter(
            question_version__question__lesson_id=source_id,
            question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam__status=ContentStatus.PUBLISHED,
        ).count()
        title = f"الاختبار الوزاري {selected_batch}"
        return {
            "kind": source_kind, "id": str(source_id),
            "assessment_type": AssessmentType.LESSON_MINISTERIAL,
            "title": title,
            "questions_count": session_count,
            "total_pool_question_count": total_count,
            "session_question_count": session_count,
            "all_years_total_pool_question_count": total_count,
            "selected_year": None,
            "target_session_size": target,
            "batch_index": selected_batch,
            "batch_count": len(batches),
            "available_years": [],
        }
    if source_kind == "unit_ministerial":
        if exam_id is None:
            raise ApplicationError(
                "A historical model is required for unit ministerial tests.",
                code="INVALID_MINISTERIAL_MODEL",
            )
        unit = Unit.objects.filter(id=source_id).first()
        exam = MinisterialExam.objects.filter(
            id=exam_id,
            subject_id=getattr(unit, "subject_id", None),
            status=ContentStatus.PUBLISHED,
        ).first()
        if exam is None:
            raise ApplicationError(
                "The requested historical model is not available.",
                code="INVALID_MINISTERIAL_MODEL",
            )
        count = MinisterialExamItem.objects.filter(
            question_version__question__unit_id=source_id,
            question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam__status=ContentStatus.PUBLISHED,
            ministerial_exam=exam,
        ).count()
        if count == 0:
            raise ApplicationError(
                "The requested model has no questions for this unit.",
                code="INVALID_MINISTERIAL_MODEL",
            )
        maximum = max(
            1, getattr(settings, "ASSESSMENT_UNIT_MINISTERIAL_MAX_SIZE", 50)
        )
        part_sizes = balanced_part_sizes(count, maximum)
        selected_part = part_index or 1
        if selected_part < 1 or selected_part > len(part_sizes):
            raise ApplicationError(
                "The requested model part is not available.",
                code="INVALID_ASSESSMENT_PART",
            )
        role_label = exam.get_exam_role_display() if exam.exam_role else None
        title = f"نموذج {exam.model_number}"
        if role_label:
            title += f" — {role_label}"
        title += " — أسئلة هذه الوحدة"
        if len(part_sizes) > 1:
            title += f" — الجزء {selected_part}"
        return {
            "kind": source_kind,
            "id": str(source_id),
            "assessment_type": AssessmentType.UNIT_TEST,
            "title": title,
            "questions_count": part_sizes[selected_part - 1],
            "total_pool_question_count": count,
            "session_question_count": part_sizes[selected_part - 1],
            "selected_year": exam.exam_year,
            "exam_id": str(exam.id),
            "exam_role": exam.exam_role,
            "model_number": exam.model_number,
            "part_index": selected_part,
            "part_count": len(part_sizes),
        }
    version = _current_version(assessment)
    count = (
        version.items.filter(
            question_version__question__status=ContentStatus.PUBLISHED
        ).count()
        if version else 0
    )
    return {
        "kind": source_kind, "id": str(source_id), "assessment_id": str(assessment.id),
        "assessment_type": assessment.assessment_type,
        "title": assessment.title,
        "questions_count": count,
        "total_pool_question_count": count,
        "session_question_count": count,
    }


def _locked_source_metadata(source_kind, source_id):
    return {
        "kind": source_kind,
        "id": str(source_id),
        "title": "محتوى غير متاح",
        "questions_count": 0,
        "total_pool_question_count": 0,
        "session_question_count": 0,
    }


def _source_access_resource(source_kind, source_id, batch_index=None):
    if source_kind == "lesson_ministerial":
        lesson = Lesson.objects.select_related("unit").filter(id=source_id).first()
        return "unit", lesson.unit if lesson else None
    if source_kind == "unit_ministerial":
        return "unit", Unit.objects.filter(id=source_id).first()
    if source_kind in _TRAINING_SOURCE_SCOPES:
        scope_type = _TRAINING_SOURCE_SCOPES[source_kind]
        sync_training_batches(scope_type, source_id)
        batch = TrainingBatch.objects.filter(
            scope_key=training_scope_key(scope_type, source_id),
            batch_index=batch_index or 1,
        ).first()
        return "training_batch", batch
    return None, None


def _assert_dynamic_source_access(*, user, source_kind, source_id, batch_index=None):
    enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
    if enrollment is None:
        raise ApplicationError(
            "No active enrollment.", code="NO_ACTIVE_ENROLLMENT"
        )
    resource_type, resource = _source_access_resource(source_kind, source_id, batch_index)
    if resource is None:
        raise ApplicationError(
            "Assessment source was not found.", code="ASSESSMENT_NOT_FOUND"
        )
    decision = check_resource_access(
        user=user,
        enrollment=enrollment,
        resource_type=resource_type,
        resource_id=str(resource.id),
    )
    if not decision.allowed:
        raise ApplicationError(
            "This content is not available under the current subscription.",
            code=decision.reason_code,
        )


def _lesson_scope(source_id, batch_index):
    return {
        "kind": "lesson_ministerial",
        "source_id": str(source_id),
        "batch": batch_index or 1,
    }


def _unit_scope(source_id, exam_id, part_index):
    return {
        "kind": "unit_ministerial",
        "source_id": str(source_id),
        "ministerial_exam_id": str(exam_id) if exam_id else None,
        "part": part_index or 1,
    }


def _select_lesson_ministerial_items(*, lesson_id, batch_index):
    lesson = Lesson.objects.filter(id=lesson_id).first()
    if lesson is None:
        raise ApplicationError("Lesson was not found.", code="ASSESSMENT_NOT_FOUND")
    batches = sync_lesson_ministerial_batches(lesson)
    selected_batch = batch_index or 1
    batch = next(
        (item for item in batches if item.batch_index == selected_batch), None
    )
    if batch is None:
        raise ApplicationError(
            "The requested lesson batch is not available.",
            code="INVALID_ASSESSMENT_BATCH",
        )
    selected = list(
        batch.batch_items.filter(
            ministerial_exam_item__question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam_item__ministerial_exam__status=ContentStatus.PUBLISHED,
        )
        .order_by("sort_order")
        .values_list("ministerial_exam_item_id", flat=True)
    )
    if not selected:
        raise ApplicationError(
            "This lesson batch has no eligible questions.",
            code="NO_ASSESSMENT_QUESTIONS",
        )
    return [str(item_id) for item_id in selected]


def _select_unit_ministerial_items(*, unit_id, exam_id, part_index):
    if exam_id is None:
        raise ApplicationError(
            "A historical model is required for unit ministerial tests.",
            code="INVALID_MINISTERIAL_MODEL",
        )
    item_ids = list(
        MinisterialExamItem.objects.filter(
            ministerial_exam_id=exam_id,
            question_version__question__unit_id=unit_id,
            question_version__question__status=ContentStatus.PUBLISHED,
            ministerial_exam__status=ContentStatus.PUBLISHED,
        ).order_by(
            "sort_order",
            "question_number",
            "id",
        ).values_list("id", flat=True)
    )
    if not item_ids:
        raise ApplicationError(
            "The requested model has no questions for this unit.",
            code="INVALID_MINISTERIAL_MODEL",
        )
    maximum = max(
        1, getattr(settings, "ASSESSMENT_UNIT_MINISTERIAL_MAX_SIZE", 50)
    )
    sizes = balanced_part_sizes(len(item_ids), maximum)
    selected_part = part_index or 1
    if selected_part < 1 or selected_part > len(sizes):
        raise ApplicationError(
            "The requested model part is not available.",
            code="INVALID_ASSESSMENT_PART",
        )
    start = sum(sizes[: selected_part - 1])
    return [str(item_id) for item_id in item_ids[start : start + sizes[selected_part - 1]]]


def _current_version(assessment):
    if assessment is None:
        return None
    return assessment.versions.filter(is_current=True).first() or assessment.versions.order_by("-version_number").first()


def _duration_seconds(version, assessment=None):
    if version is None:
        return None
    if version.timing_mode == TimingMode.CALCULATED and version.seconds_per_question:
        return version.seconds_per_question * version.question_count
    if (
        assessment is not None
        and assessment.assessment_type == AssessmentType.MINISTERIAL_EXAM
        and version.timing_mode == TimingMode.NONE
    ):
        return getattr(settings, "ASSESSMENT_SECONDS_PER_QUESTION", 60) * version.question_count
    return version.duration_minutes * 60 if version.duration_minutes else None


def _display_mode(value):
    return {"single": "one_by_one", "full": "continuous"}.get(value, value)


def _display_modes(version):
    values = getattr(version, "allowed_display_modes", None) or ["one_by_one", "continuous"]
    return [_display_mode(value) for value in values]


def _attempt_summary(attempt):
    if attempt is None:
        return None
    return {
        "attempt_id": str(attempt.id), "status": attempt.status,
        "percentage": float(attempt.percentage), "score": float(attempt.score),
        "maximum_score": float(attempt.maximum_score),
        "started_at": attempt.started_at.isoformat(),
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
    }
