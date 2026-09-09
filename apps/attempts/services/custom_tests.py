from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.assessments.models import AssessmentType
from apps.attempts.models import (
    AssessmentAttempt, AttemptQuestion, AttemptStatus, AttemptType,
)
from apps.attempts.services.selection_engine import (
    SUPPORTED_TYPES, SelectionEngine, new_selection_policy,
    normalize_selection_spec,
)
from apps.attempts.services.snapshots import build_attempt_question_snapshot
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, Lesson, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import check_resources_access_batch
from apps.ministerial_exams.models import MinisterialExam, MinisterialExamItem
from apps.question_bank.models import DifficultyLevel, QuestionVersion, SourceType
from apps.subscriptions.models import (
    FreeGenerationUse, GeneratedQuestionUse, GenerationMode,
)
from apps.subscriptions.services.generation_access import check_subject_generation_access


def custom_builder_configuration(*, user, subject_id: str) -> dict:
    enrollment = _active_enrollment(user)
    subject = Subject.objects.filter(
        id=subject_id, status=ContentStatus.PUBLISHED,
        grade_id=enrollment.grade_id, section_id=enrollment.section_id,
    ).first()
    if subject is None:
        raise ApplicationError("Subject is outside the active academic context.", code="INVALID_SCOPE")
    units = list(Unit.objects.filter(
        subject=subject, status=ContentStatus.PUBLISHED,
    ).order_by("sort_order", "id"))
    lessons = list(Lesson.objects.filter(
        unit__in=units, status=ContentStatus.PUBLISHED,
    ).select_related("unit").order_by("unit__sort_order", "sort_order", "id"))
    resources = [
        {"type": "subject", "id": subject.id},
        *({"type": "unit", "id": unit.id} for unit in units),
        *({"type": "lesson", "id": lesson.id} for lesson in lessons),
    ]
    access = check_resources_access_batch(
        user=user, enrollment=enrollment, resources=resources,
    )
    paid_whole_allowed = access[("subject", str(subject.id))].allowed
    subject_generation_access = check_subject_generation_access(
        user=user, enrollment=enrollment, subject=subject,
        mode=GenerationMode.CUSTOM,
    )
    whole_allowed = paid_whole_allowed or subject_generation_access.allowed
    accessible_units = [
        unit for unit in units if access[("unit", str(unit.id))].allowed
    ]
    accessible_unit_ids = {str(unit.id) for unit in accessible_units}
    accessible_lessons = [
        lesson for lesson in lessons
        if str(lesson.unit_id) in accessible_unit_ids
        and access[("lesson", str(lesson.id))].allowed
    ]
    if not whole_allowed and not accessible_units:
        raise ApplicationError(
            "No accessible scope is available for this subject.",
            code="INACCESSIBLE_SCOPE", status_code=403,
        )
    scope_filter = Q(question_version__question__subject=subject)
    training_scope_filter = Q(question__subject=subject)
    if not whole_allowed:
        scope_filter &= Q(question_version__question__unit_id__in=accessible_unit_ids)
        training_scope_filter &= Q(question__unit_id__in=accessible_unit_ids)
    years = list(MinisterialExamItem.objects.filter(
        scope_filter,
        question_version__question__status=ContentStatus.PUBLISHED,
        question_version__status=ContentStatus.PUBLISHED,
        question_version__question__current_version_id=F("question_version_id"),
        question_version__question__question_type__in=SUPPORTED_TYPES,
        ministerial_exam__status=ContentStatus.PUBLISHED,
    ).values_list("ministerial_exam__exam_year", flat=True).distinct().order_by("-ministerial_exam__exam_year"))
    type_values = set(MinisterialExamItem.objects.filter(
        scope_filter,
        ministerial_exam__status=ContentStatus.PUBLISHED,
        question_version__question__status=ContentStatus.PUBLISHED,
        question_version__status=ContentStatus.PUBLISHED,
        question_version__question__current_version_id=F("question_version_id"),
        question_version__question__question_type__in=SUPPORTED_TYPES,
    ).values_list("question_version__question__question_type", flat=True))
    type_values.update(QuestionVersion.objects.filter(
        training_scope_filter,
        question__source_type=SourceType.TRAINING,
        question__status=ContentStatus.PUBLISHED,
        status=ContentStatus.PUBLISHED,
        question__current_version_id=F("id"),
        question__question_type__in=SUPPORTED_TYPES,
    ).values_list("question__question_type", flat=True))
    from django.conf import settings
    return {
        "contract_version": 1,
        "subject": {"id": str(subject.id), "name": subject.name_ar},
        "whole_subject_allowed": whole_allowed,
        "subject_generation_access": {
            "allowed": subject_generation_access.allowed,
            "reason_code": subject_generation_access.reason_code,
            "is_free_generation": subject_generation_access.is_free_generation,
        },
        "units": [
            {"id": str(unit.id), "title": unit.title} for unit in accessible_units
        ],
        "lessons": [
            {"id": str(lesson.id), "unit_id": str(lesson.unit_id), "title": lesson.title}
            for lesson in accessible_lessons
        ],
        "sources": list((SourceType.MINISTERIAL, SourceType.TRAINING)),
        "ministerial_years": years,
        "difficulties": list(DifficultyLevel.values),
        "question_types": sorted(type_values),
        "count_presets": [10, 20, 30, 50],
        "max_questions": int(getattr(settings, "ASSESSMENT_CUSTOM_MAX_QUESTIONS", 50)),
        "max_duration_minutes": int(getattr(settings, "ASSESSMENT_CUSTOM_MAX_DURATION_MINUTES", 300)),
        "modes": ["practice", "exam"],
    }


def preview_custom_test(*, user, payload: dict) -> dict:
    enrollment = _active_enrollment(user)
    spec = normalize_selection_spec(payload)
    return SelectionEngine(user=user, enrollment=enrollment, spec=spec).preview()


@transaction.atomic
def create_custom_test(
    *, user, payload: dict, allow_available: bool = False,
    idempotency_key: str | None = None, parent_attempt=None,
    dynamic_assessment_type: str = AssessmentType.CUSTOM_TEST,
    dynamic_title: str = "اختبار مخصص",
    blueprint=None,
    source_scope_extra: dict | None = None,
    selection_policy_extra: dict | None = None,
    points_per_question: Decimal | None = None,
) -> AssessmentAttempt:
    if idempotency_key:
        existing = AssessmentAttempt.objects.filter(
            user=user, idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
    enrollment = _active_enrollment(user, lock=True)
    if idempotency_key:
        existing = AssessmentAttempt.objects.filter(
            user=user, idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
    spec = normalize_selection_spec(payload)
    generation_mode = (
        GenerationMode.MOCK
        if dynamic_assessment_type == AssessmentType.MOCK_EXAM
        else GenerationMode.CUSTOM
    )
    engine = SelectionEngine(
        user=user, enrollment=enrollment, spec=spec,
        generation_mode=generation_mode,
    )
    preview = engine.preview()
    if preview["maximum_creatable"] == 0:
        raise ApplicationError(
            "لا توجد حالياً أسئلة جديدة كافية لإنشاء اختبار آخر بهذه الإعدادات.",
            code="QUESTION_POOL_EXHAUSTED",
        )
    if not preview["can_create_exact"] and not allow_available:
        raise ApplicationError(
            "لا توجد حالياً أسئلة جديدة كافية لإنشاء اختبار آخر بهذه الإعدادات.",
            code="QUESTION_POOL_EXHAUSTED",
        )
    actual_count = spec.count if preview["can_create_exact"] else preview["maximum_creatable"]
    policy = new_selection_policy()
    selected, policy_snapshot = engine.select(count=actual_count, policy=policy)

    ministerial_ids = [
        item.ministerial_exam_item_id for item in selected
        if item.ministerial_exam_item_id
    ]
    version_ids = [item.question_version_id for item in selected]
    occurrences = {
        str(item.id): item for item in MinisterialExamItem.objects.filter(
            id__in=ministerial_ids,
        ).select_related("ministerial_exam", "question_version__question").prefetch_related(
            "question_version__options", "question_version__stimulus_links__stimulus",
            "question_version__assets",
        )
    }
    versions = {
        str(item.id): item for item in QuestionVersion.objects.filter(
            id__in=version_ids,
        ).select_related("question").prefetch_related(
            "options", "stimulus_links__stimulus", "assets",
        )
    }
    if len(versions) != len(set(version_ids)):
        raise ApplicationError(
            "A selected question became stale before the attempt was frozen.",
            code="STALE_QUESTION_REFERENCE", status_code=409,
        )

    expires_at = (
        timezone.now() + timedelta(minutes=spec.duration_minutes)
        if spec.duration_minutes else None
    )
    attempt = AssessmentAttempt.objects.create(
        user=user,
        study_enrollment=enrollment,
        assessment=None,
        assessment_version=None,
        parent_attempt=parent_attempt,
        attempt_type=AttemptType.NORMAL,
        mode=spec.mode,
        status=AttemptStatus.IN_PROGRESS,
        display_mode="single",
        contract_version=1,
        source_scope={
            "kind": dynamic_assessment_type,
            "subject_id": spec.subject_id,
            "scope_mode": spec.scope_mode,
            **(source_scope_extra or {}),
        },
        dynamic_assessment_type=dynamic_assessment_type,
        dynamic_title=dynamic_title,
        dynamic_subject=engine.subject,
        blueprint=blueprint,
        selection_spec_snapshot=spec.to_snapshot(),
        selection_policy_snapshot={
            **policy_snapshot,
            "requested_count": spec.count,
            "created_with_available_count": actual_count != spec.count,
            **(selection_policy_extra or {}),
        },
        feedback_policy="immediate" if spec.mode == "practice" else "deferred",
        timing_mode="fixed" if spec.duration_minutes else "none",
        duration_seconds=(spec.duration_minutes or 0) * 60,
        questions_shuffled=True,
        options_shuffled=True,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
    )
    attempt_questions = []
    total = Decimal("0.00")
    for index, identity in enumerate(selected, 1):
        question_version = versions[identity.question_version_id]
        question = question_version.question
        occurrence = (
            occurrences[identity.ministerial_exam_item_id]
            if identity.ministerial_exam_item_id else None
        )
        options = list(question_version.options.all())
        if question.question_type != "true_false":
            random.Random(f"{policy.seed}:{identity.question_version_id}:{index}").shuffle(options)
        metadata = {
            "question_id": str(question.id),
            "question_version_id": str(question_version.id),
        }
        if occurrence:
            exam = occurrence.ministerial_exam
            metadata.update({
                "year": exam.exam_year,
                "exam_role": exam.exam_role,
                "model_number": exam.model_number,
                "question_number": occurrence.question_number,
                "ministerial_exam_id": str(exam.id),
                "ministerial_exam_item_id": str(occurrence.id),
            })
            points = occurrence.points
        else:
            metadata.update(dict(question.metadata or {}))
            points = question_version.points
        if points_per_question is not None:
            points = points_per_question
        snapshot = build_attempt_question_snapshot(
            question_version=question_version,
            points=points,
            options=options,
            source_metadata=metadata,
        )
        attempt_questions.append(AttemptQuestion(
            attempt=attempt,
            question_version=question_version,
            ministerial_exam_item=occurrence,
            source_type=identity.source_type,
            sort_order=index,
            points=points,
            is_reference=False,
            options_order_snapshot=[option.option_key for option in options],
            source_metadata_snapshot=metadata,
            question_snapshot=snapshot,
        ))
        total += points
    AttemptQuestion.objects.bulk_create(attempt_questions)
    logical_question_ids = {str(versions[item.question_version_id].question_id) for item in selected}
    GeneratedQuestionUse.objects.bulk_create([
        GeneratedQuestionUse(
            user=user,
            academic_year_id=enrollment.academic_year_id,
            question_id=question_id,
            mode=generation_mode,
            attempt=attempt,
        )
        for question_id in logical_question_ids
    ])
    if (
        spec.scope_mode == "subject"
        and engine.generation_access is not None
        and engine.generation_access.is_free_generation
    ):
        FreeGenerationUse.objects.create(
            user=user,
            academic_year_id=enrollment.academic_year_id,
            subject=engine.subject,
            mode=generation_mode,
            attempt=attempt,
        )
    attempt.maximum_score = total
    attempt.official_maximum_score = total
    attempt.save(update_fields=["maximum_score", "official_maximum_score"])
    return attempt


def new_custom_test_with_same_settings(
    *, user, parent_attempt_id: str, idempotency_key: str | None = None,
):
    parent = AssessmentAttempt.objects.filter(
        id=parent_attempt_id, user=user,
        status__in=["submitted", "evaluated", "pending_review", "expired"],
    ).first()
    if parent is None or not parent.selection_spec_snapshot:
        raise ApplicationError(
            "The source custom test is unavailable.", code="PARENT_ATTEMPT_INVALID",
        )
    if parent.dynamic_assessment_type == AssessmentType.MOCK_EXAM:
        from apps.attempts.services.mock_exams import new_mock_from_attempt
        return new_mock_from_attempt(
            user=user, parent=parent, idempotency_key=idempotency_key,
        )
    if parent.dynamic_assessment_type != AssessmentType.CUSTOM_TEST:
        raise ApplicationError(
            "The source dynamic assessment is invalid.", code="PARENT_ATTEMPT_INVALID",
        )
    return create_custom_test(
        user=user, payload=parent.selection_spec_snapshot,
        allow_available=bool((parent.selection_policy_snapshot or {}).get("created_with_available_count")),
        idempotency_key=idempotency_key, parent_attempt=parent,
    )


def _active_enrollment(user, lock=False):
    query = StudyEnrollment.objects.filter(user=user, is_active=True)
    if lock:
        query = query.select_for_update()
    enrollment = query.first()
    if enrollment is None:
        raise ApplicationError("No active enrollment.", code="NO_ACTIVE_ENROLLMENT")
    return enrollment
