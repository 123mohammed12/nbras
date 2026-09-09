from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from django.db.models import Q
from django.utils import timezone

from apps.assessments.models import Assessment, AssessmentType
from apps.attempts.models import AssessmentAttempt, AttemptStatus
from apps.content.models import FlashcardDeck, LessonExplanation, Summary, SummaryType
from apps.curriculum.models import ContentStatus, Lesson, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import (
    AccessContext,
    check_resource_access,
    check_resources_access_batch,
)
from apps.progress.models import (
    LearningResourceProgress,
    LessonProgress,
    ProgressStatus,
    SubjectProgress,
    UnitProgress,
)
from apps.progress.services.progress_selectors import (
    calculate_accessible_completion_for_subjects,
    calculate_accessible_completion_for_units,
    calculate_accessible_completion_for_lessons,
)
from apps.progress.services.recalculation import (
    compute_lesson_accessible_completion,
    compute_unit_accessible_completion,
)


EVIDENCE_STATUSES = (
    AttemptStatus.SUBMITTED,
    AttemptStatus.EVALUATED,
    AttemptStatus.PENDING_REVIEW,
)
ACTIVE_ATTEMPT_STATUSES = (
    AttemptStatus.CREATED,
    AttemptStatus.IN_PROGRESS,
    AttemptStatus.PAUSED,
)


def get_active_enrollment(user) -> StudyEnrollment | None:
    return (
        StudyEnrollment.objects.filter(user=user, is_active=True)
        .select_related("grade", "section")
        .first()
    )


def _status(percentage: float) -> str:
    if percentage >= 100:
        return ProgressStatus.COMPLETED
    if percentage > 0:
        return ProgressStatus.IN_PROGRESS
    return ProgressStatus.NOT_STARTED


def _completion(row, *, accessible: float) -> dict:
    percentage = float(row.completion_percentage) if row else 0.0
    return {
        "status": row.status if row else _status(percentage),
        "completion_percentage": percentage,
        "accessible_completion_percentage": float(accessible),
        "completed_at": row.completed_at if row else None,
        "last_activity_at": row.last_activity_at if row else None,
    }


def _attempts_for_scope(*, user, enrollment, subject_id=None, unit_id=None, lesson_id=None):
    filters = {
        "user": user,
        "study_enrollment": enrollment,
        # FE-05 remains intentionally assessment-keyed in AR-04. Dynamic custom
        # attempts are visible in History, but do not enter this legacy metric.
        "assessment__isnull": False,
        "status__in": EVIDENCE_STATUSES,
        "submitted_at__isnull": False,
        "maximum_score__gt": 0,
        "attempt_type__in": ("normal", "retry_full"),
    }
    if lesson_id:
        filters["assessment__lesson_id"] = lesson_id
    elif unit_id:
        filters["assessment__unit_id"] = unit_id
    elif subject_id:
        filters["assessment__subject_id"] = subject_id
    return (
        AssessmentAttempt.objects.filter(**filters)
        .select_related("assessment", "assessment__subject", "assessment__unit", "assessment__lesson")
        .order_by("-submitted_at", "-created_at")
    )


def _available_assessments(*, enrollment, subject_id=None, unit_id=None, lesson_id=None) -> bool:
    query = Assessment.objects.filter(
        status=ContentStatus.PUBLISHED,
        subject__grade_id=enrollment.grade_id,
        subject__section_id=enrollment.section_id,
    )
    if lesson_id:
        query = query.filter(lesson_id=lesson_id)
    elif unit_id:
        query = query.filter(unit_id=unit_id)
    elif subject_id:
        query = query.filter(subject_id=subject_id)
    return query.exists()


def performance_summary(*, user, enrollment, subject_id=None, unit_id=None, lesson_id=None) -> dict:
    """Best completed attempt per assessment, aggregated by gradable points.

    The policy is intentionally backend-owned. Official essay-inclusive totals are
    never used as the interactive performance denominator.
    """
    attempts = list(
        _attempts_for_scope(
            user=user,
            enrollment=enrollment,
            subject_id=subject_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
        )
    )
    return _performance_from_attempts(
        attempts,
        has_available=_available_assessments(
            enrollment=enrollment,
            subject_id=subject_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
        ),
    )


def _performance_from_attempts(attempts, *, has_available: bool) -> dict:
    best_by_assessment: dict[str, AssessmentAttempt] = {}
    for attempt in attempts:
        key = str(attempt.assessment_id)
        current = best_by_assessment.get(key)
        ratio = Decimal(attempt.score) / Decimal(attempt.maximum_score)
        current_ratio = (
            Decimal(current.score) / Decimal(current.maximum_score) if current else Decimal("-1")
        )
        if ratio > current_ratio:
            best_by_assessment[key] = attempt

    earned = sum((Decimal(a.score) for a in best_by_assessment.values()), Decimal("0"))
    available = sum((Decimal(a.maximum_score) for a in best_by_assessment.values()), Decimal("0"))
    percentage = round(float((earned / available) * 100), 2) if available > 0 else None
    latest = attempts[0] if attempts else None
    return {
        "has_evidence": bool(attempts),
        "has_available_assessments": has_available,
        "percentage": percentage,
        "earned_points": float(earned) if attempts else None,
        "available_points": float(available) if attempts else None,
        "attempts_count": len(attempts),
        "contributing_assessments_count": len(best_by_assessment),
        "latest_result": _attempt_summary(latest) if latest else None,
    }


def _attempt_summary(attempt: AssessmentAttempt) -> dict:
    if attempt.assessment_id is None or attempt.dynamic_assessment_type:
        spec = attempt.selection_spec_snapshot or {}
        scope = spec.get("scope") or {}
        subject = attempt.dynamic_subject
        source_scope = attempt.source_scope or {}
        return {
            "attempt_id": str(attempt.id),
            "assessment_id": None,
            "title": attempt.dynamic_title,
            "assessment_type": attempt.dynamic_assessment_type,
            "subject_id": str(attempt.dynamic_subject_id),
            "subject_name": subject.name_ar if subject else "",
            "unit_id": (
                scope.get("unit_ids", [None])[0]
                if len(scope.get("unit_ids") or []) == 1
                else source_scope.get("unit_id")
            ),
            "lesson_id": (
                scope.get("lesson_ids", [None])[0]
                if len(scope.get("lesson_ids") or []) == 1
                else source_scope.get("lesson_id")
            ),
            "score": float(attempt.score),
            "maximum_score": float(attempt.maximum_score),
            "official_maximum_score": float(attempt.official_maximum_score),
            "percentage": float(attempt.percentage),
            "attempt_type": attempt.attempt_type,
            "submitted_at": attempt.submitted_at,
        }
    return {
        "attempt_id": str(attempt.id),
        "assessment_id": str(attempt.assessment_id),
        "title": attempt.assessment.title,
        "assessment_type": attempt.assessment.assessment_type,
        "subject_id": str(attempt.assessment.subject_id),
        "subject_name": attempt.assessment.subject.name_ar,
        "unit_id": str(attempt.assessment.unit_id) if attempt.assessment.unit_id else None,
        "lesson_id": str(attempt.assessment.lesson_id) if attempt.assessment.lesson_id else None,
        "score": float(attempt.score),
        "maximum_score": float(attempt.maximum_score),
        "official_maximum_score": float(attempt.official_maximum_score),
        "percentage": float(attempt.percentage),
        "attempt_type": attempt.attempt_type,
        "submitted_at": attempt.submitted_at,
    }


def _access_map(user, enrollment, resources, context):
    return check_resources_access_batch(
        user=user, enrollment=enrollment, resources=resources, context=context
    )


def _decision(access_map, resource_type, resource_id):
    decision = access_map.get((resource_type, str(resource_id)))
    return decision.to_dict() if decision else None


def _subject_decision(access_map, subject_id, context):
    data = _decision(access_map, "subject", subject_id)
    if data and not data["allowed"] and any(
        str(policy.subject_id) == str(subject_id) and policy.free_unit_id
        for policy in context.free_access_policies
    ):
        return {
            **data,
            "access": True,
            "allowed": True,
            "reason_code": "PARTIAL_FREE_ACCESS",
            "source": "free_unit",
            "scope_type": "subject",
            "scope_id": str(subject_id),
            "requires_subscription": True,
            "upgrade_required": True,
        }
    return data


def _continue_candidates(*, user, enrollment, subject_id=None, unit_id=None, lesson_id=None):
    now = timezone.now()
    attempt_query = AssessmentAttempt.objects.filter(
        user=user,
        study_enrollment=enrollment,
        status__in=ACTIVE_ATTEMPT_STATUSES,
        assessment__status=ContentStatus.PUBLISHED,
    ).select_related("assessment", "assessment_version", "assessment__subject", "assessment__unit", "assessment__lesson")
    resource_query = LearningResourceProgress.objects.filter(
        user=user,
        study_enrollment=enrollment,
        status=ProgressStatus.IN_PROGRESS,
    ).select_related("subject", "unit", "lesson")
    for query in (attempt_query, resource_query):
        if lesson_id:
            query.query.add_q(Q(lesson_id=lesson_id) if query.model is LearningResourceProgress else Q(assessment__lesson_id=lesson_id))
        elif unit_id:
            query.query.add_q(Q(unit_id=unit_id) if query.model is LearningResourceProgress else Q(assessment__unit_id=unit_id))
        elif subject_id:
            query.query.add_q(Q(subject_id=subject_id) if query.model is LearningResourceProgress else Q(assessment__subject_id=subject_id))

    candidates = []
    for attempt in attempt_query.order_by("-last_activity_at")[:10]:
        if attempt.expires_at and attempt.expires_at <= now:
            continue
        assessment = attempt.assessment
        timed = bool(attempt.expires_at or attempt.timing_mode != "none")
        candidates.append(
            {
                "priority": 300 if timed else 200,
                "last_activity_at": attempt.last_activity_at,
                "access_type": "assessment",
                "access_id": str(assessment.id),
                "payload": {
                    "type": "assessment",
                    "resource_id": str(assessment.id),
                    "attempt_id": str(attempt.id),
                    "title": assessment.title,
                    "subtitle": "اختبار جارٍ — الوقت مستمر" if timed else "اختبار قيد التقدم",
                    "subject_id": str(assessment.subject_id),
                    "unit_id": str(assessment.unit_id) if assessment.unit_id else None,
                    "lesson_id": str(assessment.lesson_id) if assessment.lesson_id else None,
                    "progress": None,
                    "is_timed": timed,
                    "submission_pending": False,
                    "last_activity_at": attempt.last_activity_at,
                },
            }
        )
    for progress in resource_query.order_by("-last_activity_at")[:10]:
        candidates.append(
            {
                "priority": 100,
                "last_activity_at": progress.last_activity_at,
                "access_type": progress.resource_type,
                "access_id": str(progress.resource_id),
                "payload": {
                    "type": progress.resource_type,
                    "resource_id": str(progress.resource_id),
                    "attempt_id": None,
                    "title": (progress.resource_snapshot or {}).get("title") or _resource_title(progress),
                    "subtitle": _resource_subtitle(progress.resource_type),
                    "subject_id": str(progress.subject_id) if progress.subject_id else None,
                    "unit_id": str(progress.unit_id) if progress.unit_id else None,
                    "lesson_id": str(progress.lesson_id) if progress.lesson_id else None,
                    "progress": float(progress.completion_percentage),
                    "is_timed": False,
                    "submission_pending": False,
                    "last_activity_at": progress.last_activity_at,
                },
            }
        )
    return candidates


def _resource_title(progress):
    if progress.lesson:
        return progress.lesson.title
    if progress.unit:
        return progress.unit.title
    if progress.subject:
        return progress.subject.name_ar
    return "نشاط تعليمي"


def _resource_subtitle(resource_type):
    return {
        "lesson_explanation": "متابعة شرح الدرس",
        "summary": "متابعة القراءة",
        "flashcard_deck": "متابعة البطاقات الذكية",
    }.get(resource_type, "متابعة التعلم")


def resolve_continue_item(*, user, enrollment, subject_id=None, unit_id=None, lesson_id=None, context=None):
    context = context or AccessContext.build(user=user, enrollment=enrollment)
    candidates = _continue_candidates(
        user=user,
        enrollment=enrollment,
        subject_id=subject_id,
        unit_id=unit_id,
        lesson_id=lesson_id,
    )
    if not candidates:
        return None
    access_map = _access_map(
        user,
        enrollment,
        [{"type": item["access_type"], "id": item["access_id"]} for item in candidates],
        context,
    )
    valid = [
        item for item in candidates
        if access_map.get((item["access_type"], item["access_id"]))
        and access_map[(item["access_type"], item["access_id"])].allowed
    ]
    if not valid:
        return None
    selected = max(valid, key=lambda item: (item["priority"], item["last_activity_at"]))
    return selected["payload"]


def recent_activity(*, user, enrollment, subject_id=None, unit_id=None, lesson_id=None, limit=3):
    attempts = completed_attempt_history(user=user, enrollment=enrollment)
    if lesson_id:
        attempts = attempts.filter(
            Q(assessment__lesson_id=lesson_id)
            | Q(attempt_questions__question_version__question__lesson_id=lesson_id)
        )
    elif unit_id:
        attempts = attempts.filter(
            Q(assessment__unit_id=unit_id)
            | Q(attempt_questions__question_version__question__unit_id=unit_id)
        )
    elif subject_id:
        attempts = attempts.filter(
            Q(assessment__subject_id=subject_id)
            | Q(dynamic_subject_id=subject_id)
            | Q(attempt_questions__question_version__question__subject_id=subject_id)
        )
    attempts = list(attempts.distinct()[: limit * 2])
    resources = LearningResourceProgress.objects.filter(
        user=user,
        study_enrollment=enrollment,
        last_activity_at__isnull=False,
    ).select_related("subject", "unit", "lesson")
    if lesson_id:
        resources = resources.filter(lesson_id=lesson_id)
    elif unit_id:
        resources = resources.filter(unit_id=unit_id)
    elif subject_id:
        resources = resources.filter(subject_id=subject_id)
    items = []
    for attempt in attempts:
        title = attempt.assessment_title or "اختبار"
        items.append(
            {
                "type": "assessment_completed",
                "resource_id": str(attempt.id),
                "title": f"أكملت {title}",
                "subtitle": f"{float(attempt.percentage):g}%",
                "occurred_at": attempt.submitted_at,
                "attempt_id": str(attempt.id),
                "assessment_kind": attempt.assessment_kind,
                "is_remediation": attempt.assessment_kind in (
                    AssessmentType.WRONG_ANSWERS_TEST, "weakness_practice"
                ),
            }
        )
    seen = set()
    for progress in resources.order_by("-last_activity_at")[: limit * 3]:
        key = (progress.resource_type, progress.resource_id)
        if key in seen:
            continue
        seen.add(key)
        completed = progress.status == ProgressStatus.COMPLETED
        items.append(
            {
                "type": f"{progress.resource_type}_{'completed' if completed else 'resumed'}",
                "resource_id": progress.resource_id,
                "title": (progress.resource_snapshot or {}).get("title") or _resource_title(progress),
                "subtitle": "مكتمل" if completed else "تمت المتابعة",
                "occurred_at": progress.completed_at or progress.last_activity_at,
                "attempt_id": None,
            }
        )
    items.sort(key=lambda item: item["occurred_at"], reverse=True)
    return items[:limit]


def progress_overview(*, user, enrollment):
    from apps.progress.services.mastery import mastery_overview
    from apps.analytics.services.student_analytics import student_analytics
    context = AccessContext.build(user=user, enrollment=enrollment)
    subjects = list(
        Subject.objects.filter(
            grade_id=enrollment.grade_id,
            section_id=enrollment.section_id,
            status=ContentStatus.PUBLISHED,
        ).order_by("sort_order", "id")
    )
    subject_rows = {
        str(row.subject_id): row
        for row in SubjectProgress.objects.filter(
            user=user, study_enrollment=enrollment, subject__in=subjects
        )
    }
    accessible = calculate_accessible_completion_for_subjects(
        user, enrollment, subjects, context=context
    )
    access_map = _access_map(
        user,
        enrollment,
        [{"type": "subject", "id": str(subject.id)} for subject in subjects],
        context,
    )
    all_attempts = list(_attempts_for_scope(user=user, enrollment=enrollment))
    attempts_by_subject = defaultdict(list)
    for attempt in all_attempts:
        attempts_by_subject[str(attempt.assessment.subject_id)].append(attempt)
    available_subjects = set(
        Assessment.objects.filter(
            status=ContentStatus.PUBLISHED,
            subject__in=subjects,
        ).values_list("subject_id", flat=True)
    )
    items = []
    for subject in subjects:
        sid = str(subject.id)
        row = subject_rows.get(sid)
        items.append(
            {
                "subject_id": sid,
                "subject_name": subject.name_ar,
                "sort_order": subject.sort_order,
                "icon_path": subject.icon_path.url if subject.icon_path else None,
                "access": _subject_decision(access_map, sid, context),
                "completion": _completion(row, accessible=accessible.get(sid, 0.0)),
                "performance": _performance_from_attempts(
                    attempts_by_subject.get(sid, []),
                    has_available=subject.id in available_subjects,
                ),
            }
        )
    overall = round(
        sum(item["completion"]["completion_percentage"] for item in items) / len(items), 2
    ) if items else 0.0
    accessible_items = [
        item
        for item in items
        if item["access"] and item["access"].get("allowed") is True
    ]
    accessible_overall = round(
        sum(
            item["completion"]["accessible_completion_percentage"]
            for item in accessible_items
        )
        / len(accessible_items),
        2,
    ) if accessible_items else 0.0
    mastery = mastery_overview(user=user, enrollment=enrollment)
    payload = {
        "enrollment": {
            "id": str(enrollment.id),
            "grade_name": enrollment.grade.name_ar,
            "section_name": enrollment.section.name_ar,
        },
        "completion": {
            "status": _status(overall),
            "completion_percentage": overall,
            "accessible_completion_percentage": accessible_overall,
            "completed_at": None,
            "last_activity_at": max(
                (item["completion"]["last_activity_at"] for item in items if item["completion"]["last_activity_at"]),
                default=None,
            ),
        },
        "performance": _performance_from_attempts(
            all_attempts, has_available=bool(available_subjects)
        ),
        "mastery": mastery,
        "analytics": student_analytics(
            user=user, enrollment=enrollment, mastery=mastery
        ),
        "subjects": items,
        "continue_item": resolve_continue_item(
            user=user, enrollment=enrollment, context=context
        ),
        "recent_activity": recent_activity(user=user, enrollment=enrollment),
        "assessment_preview": [
            _attempt_summary(attempt)
            for attempt in all_attempts[:3]
        ],
        "updated_at": timezone.now(),
    }
    # Kept for API consumers predating FE-05. New clients use completion.*.
    payload.update(
        {
            "overall_completion_percentage": overall,
            "accessible_completion_percentage": accessible_overall,
            "subjects_count": len(items),
            "completed_subjects": sum(
                1 for item in items if item["completion"]["completion_percentage"] >= 100
            ),
            "total_learning_seconds": sum(
                row.time_spent_seconds for row in subject_rows.values()
            ),
            "active_study_enrollment": str(enrollment.id),
        }
    )
    return payload


def _assert_scope(enrollment, subject):
    return (
        str(subject.grade_id) == str(enrollment.grade_id)
        and str(subject.section_id) == str(enrollment.section_id)
        and subject.status == ContentStatus.PUBLISHED
    )


def subject_progress_details(*, user, enrollment, subject_id):
    from apps.progress.services.mastery import mastery_for_scope
    from apps.analytics.services.student_analytics import student_analytics
    subject = Subject.objects.filter(id=subject_id).first()
    if not subject or not _assert_scope(enrollment, subject):
        return None, "not_found"
    context = AccessContext.build(user=user, enrollment=enrollment)
    decision = check_resource_access(
        user=user, enrollment=enrollment, resource_type="subject", resource_id=subject_id, context=context
    )
    if not decision.allowed and not any(
        str(policy.subject_id) == str(subject_id) for policy in context.free_access_policies
    ):
        return None, "denied"
    units = list(Unit.objects.filter(subject=subject, status=ContentStatus.PUBLISHED).order_by("sort_order", "id"))
    unit_rows = {
        str(row.unit_id): row for row in UnitProgress.objects.filter(
            user=user, study_enrollment=enrollment, unit__in=units
        )
    }
    unit_access = _access_map(user, enrollment, [{"type": "unit", "id": str(u.id)} for u in units], context)
    unit_accessible = calculate_accessible_completion_for_units(
        user, enrollment, units, context=context
    )
    scoped_attempts = list(_attempts_for_scope(user=user, enrollment=enrollment, subject_id=str(subject.id)))
    attempts_by_unit = defaultdict(list)
    for attempt in scoped_attempts:
        if attempt.assessment.unit_id:
            attempts_by_unit[str(attempt.assessment.unit_id)].append(attempt)
    available_unit_ids = set(
        str(value) for value in Assessment.objects.filter(
            status=ContentStatus.PUBLISHED, subject=subject, unit__in=units
        ).values_list("unit_id", flat=True)
    )
    subject_row = SubjectProgress.objects.filter(
        user=user, study_enrollment=enrollment, subject=subject
    ).first()
    accessible = calculate_accessible_completion_for_subjects(user, enrollment, [subject], context=context).get(str(subject.id), 0.0)
    unit_items = []
    for unit in units:
        uid = str(unit.id)
        allowed = bool(unit_access.get(("unit", uid)) and unit_access[("unit", uid)].allowed)
        unit_items.append({
            "unit_id": uid,
            "title": unit.title,
            "sort_order": unit.sort_order,
            "access": _decision(unit_access, "unit", uid),
            "completion": _completion(
                unit_rows.get(uid),
                accessible=unit_accessible.get(uid, 0.0) if allowed else 0.0,
            ),
            "performance": _performance_from_attempts(
                attempts_by_unit.get(uid, []), has_available=uid in available_unit_ids
            ),
        })
    mastery = mastery_for_scope(
        user=user, enrollment=enrollment, scope_type="subject",
        scope_id=subject.id, title=subject.name_ar,
    )
    return {
        "scope": {"type": "subject", "id": str(subject.id), "title": subject.name_ar, "subject_id": str(subject.id)},
        "access": decision.to_dict(),
        "completion": _completion(subject_row, accessible=accessible),
        "performance": performance_summary(user=user, enrollment=enrollment, subject_id=str(subject.id)),
        "mastery": mastery,
        "analytics": student_analytics(
            user=user, enrollment=enrollment, mastery=mastery, subject=subject
        ),
        "continue_item": resolve_continue_item(user=user, enrollment=enrollment, subject_id=str(subject.id), context=context),
        "children": unit_items,
        "recent_activity": recent_activity(user=user, enrollment=enrollment, subject_id=str(subject.id)),
    }, None


def unit_progress_details(*, user, enrollment, unit_id):
    from apps.progress.services.mastery import mastery_for_scope
    from apps.analytics.services.student_analytics import student_analytics
    unit = Unit.objects.select_related("subject").filter(id=unit_id, status=ContentStatus.PUBLISHED).first()
    if not unit or not _assert_scope(enrollment, unit.subject):
        return None, "not_found"
    context = AccessContext.build(user=user, enrollment=enrollment)
    decision = check_resource_access(user=user, enrollment=enrollment, resource_type="unit", resource_id=unit_id, context=context)
    if not decision.allowed:
        return None, "denied"
    lessons = list(Lesson.objects.filter(unit=unit, status=ContentStatus.PUBLISHED).order_by("sort_order", "id"))
    lesson_rows = {str(row.lesson_id): row for row in LessonProgress.objects.filter(user=user, study_enrollment=enrollment, lesson__in=lessons)}
    lesson_access = _access_map(user, enrollment, [{"type": "lesson", "id": str(l.id)} for l in lessons], context)
    lesson_accessible = calculate_accessible_completion_for_lessons(
        user, enrollment, lessons, context=context
    )
    scoped_attempts = list(_attempts_for_scope(user=user, enrollment=enrollment, unit_id=str(unit.id)))
    attempts_by_lesson = defaultdict(list)
    for attempt in scoped_attempts:
        if attempt.assessment.lesson_id:
            attempts_by_lesson[str(attempt.assessment.lesson_id)].append(attempt)
    available_lesson_ids = set(
        str(value) for value in Assessment.objects.filter(
            status=ContentStatus.PUBLISHED, unit=unit, lesson__in=lessons
        ).values_list("lesson_id", flat=True)
    )
    unit_row = UnitProgress.objects.filter(user=user, study_enrollment=enrollment, unit=unit).first()
    children = []
    for lesson in lessons:
        lid = str(lesson.id)
        allowed = bool(lesson_access.get(("lesson", lid)) and lesson_access[("lesson", lid)].allowed)
        children.append({
            "lesson_id": lid,
            "title": lesson.title,
            "sort_order": lesson.sort_order,
            "access": _decision(lesson_access, "lesson", lid),
            "completion": _completion(
                lesson_rows.get(lid),
                accessible=lesson_accessible.get(lid, 0.0) if allowed else 0.0,
            ),
            "performance": _performance_from_attempts(
                attempts_by_lesson.get(lid, []), has_available=lid in available_lesson_ids
            ),
        })
    mastery = mastery_for_scope(
        user=user, enrollment=enrollment, scope_type="unit",
        scope_id=unit.id, title=unit.title,
    )
    return {
        "scope": {"type": "unit", "id": str(unit.id), "title": unit.title, "subject_id": str(unit.subject_id)},
        "access": decision.to_dict(),
        "completion": _completion(unit_row, accessible=compute_unit_accessible_completion(user=user, enrollment=enrollment, unit_id=str(unit.id), context=context)),
        "performance": performance_summary(user=user, enrollment=enrollment, unit_id=str(unit.id)),
        "mastery": mastery,
        "analytics": student_analytics(
            user=user, enrollment=enrollment, mastery=mastery,
            subject=unit.subject, unit=unit,
        ),
        "continue_item": resolve_continue_item(user=user, enrollment=enrollment, unit_id=str(unit.id), context=context),
        "children": children,
        "recent_activity": recent_activity(user=user, enrollment=enrollment, unit_id=str(unit.id)),
    }, None


def _resource_progress_map(user, enrollment, resources: Iterable[tuple[str, str]]):
    pairs = list(resources)
    by_type = defaultdict(list)
    for resource_type, resource_id in pairs:
        by_type[resource_type].append(resource_id)
    query = Q(pk__in=[])
    for resource_type, resource_ids in by_type.items():
        query |= Q(resource_type=resource_type, resource_id__in=resource_ids)
    rows = LearningResourceProgress.objects.filter(user=user, study_enrollment=enrollment).filter(query)
    return {(row.resource_type, row.resource_id): row for row in rows}


def lesson_progress_details(*, user, enrollment, lesson_id):
    from apps.progress.services.mastery import mastery_for_scope
    from apps.analytics.services.student_analytics import student_analytics
    lesson = Lesson.objects.select_related("unit__subject").filter(id=lesson_id, status=ContentStatus.PUBLISHED).first()
    if not lesson or not _assert_scope(enrollment, lesson.unit.subject):
        return None, "not_found"
    context = AccessContext.build(user=user, enrollment=enrollment)
    decision = check_resource_access(user=user, enrollment=enrollment, resource_type="lesson", resource_id=lesson_id, context=context)
    if not decision.allowed:
        return None, "denied"
    explanation = LessonExplanation.objects.filter(lesson=lesson, status=ContentStatus.PUBLISHED).first()
    summaries = list(Summary.objects.filter(lesson=lesson, status=ContentStatus.PUBLISHED, summary_type__in=(SummaryType.LESSON, SummaryType.QUICK_REVIEW)).order_by("sort_order", "id"))
    from django.db.models import Count
    decks = list(
        FlashcardDeck.objects.filter(lesson=lesson, status=ContentStatus.PUBLISHED)
        .annotate(active_cards_count=Count("cards", filter=Q(cards__is_active=True)))
        .order_by("sort_order", "id")
    )
    resources = []
    if explanation:
        resources.append(("lesson_explanation", str(explanation.id)))
    resources += [("summary", str(summary.id)) for summary in summaries]
    resources += [("flashcard_deck", str(deck.id)) for deck in decks]
    progress_map = _resource_progress_map(user, enrollment, resources)
    activities = []
    if explanation:
        activities.append(_activity("lesson_explanation", explanation.id, explanation.title or lesson.title, progress_map))
    for summary in summaries:
        activities.append(_activity("summary", summary.id, summary.title, progress_map, subtype=summary.summary_type))
    for deck in decks:
        item = _activity("flashcard_deck", deck.id, deck.title, progress_map)
        item["cards_count"] = deck.active_cards_count
        activities.append(item)
    lesson_row = LessonProgress.objects.filter(user=user, study_enrollment=enrollment, lesson=lesson).first()
    assessments = list(Assessment.objects.filter(lesson=lesson, status=ContentStatus.PUBLISHED).order_by("created_at"))
    lesson_attempts = list(
        _attempts_for_scope(
            user=user, enrollment=enrollment, lesson_id=str(lesson.id)
        )
    )
    attempts_by_assessment = defaultdict(list)
    for attempt in lesson_attempts:
        attempts_by_assessment[str(attempt.assessment_id)].append(attempt)
    assessment_items = []
    for assessment in assessments:
        attempts = attempts_by_assessment.get(str(assessment.id), [])
        assessment_items.append({
            "assessment_id": str(assessment.id),
            "title": assessment.title,
            "assessment_type": assessment.assessment_type,
            "attempts_count": len(attempts),
            "latest_result": _attempt_summary(attempts[0]) if attempts else None,
        })
    mastery = mastery_for_scope(
        user=user, enrollment=enrollment, scope_type="lesson",
        scope_id=lesson.id, title=lesson.title,
    )
    return {
        "scope": {
            "type": "lesson", "id": str(lesson.id), "title": lesson.title,
            "subject_id": str(lesson.unit.subject_id), "unit_id": str(lesson.unit_id),
        },
        "access": decision.to_dict(),
        "completion": _completion(lesson_row, accessible=compute_lesson_accessible_completion(user=user, enrollment=enrollment, lesson_id=str(lesson.id), context=context)),
        "performance": performance_summary(user=user, enrollment=enrollment, lesson_id=str(lesson.id)),
        "mastery": mastery,
        "analytics": student_analytics(
            user=user, enrollment=enrollment, mastery=mastery,
            subject=lesson.unit.subject, unit=lesson.unit, lesson=lesson,
        ),
        "continue_item": resolve_continue_item(user=user, enrollment=enrollment, lesson_id=str(lesson.id), context=context),
        "learning_activities": activities,
        "assessments": assessment_items,
        "recent_activity": recent_activity(user=user, enrollment=enrollment, lesson_id=str(lesson.id)),
    }, None


def _activity(resource_type, resource_id, title, progress_map, subtype=None):
    row = progress_map.get((resource_type, str(resource_id)))
    return {
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "subtype": subtype,
        "title": title,
        "status": row.status if row else ProgressStatus.NOT_STARTED,
        "completion_percentage": float(row.completion_percentage) if row else 0.0,
        "pending_sync": False,
    }


def completed_attempt_history(*, user, enrollment, category=None, subject_id=None):
    query = AssessmentAttempt.objects.filter(
        user=user,
        study_enrollment=enrollment,
        status__in=EVIDENCE_STATUSES,
        submitted_at__isnull=False,
    ).select_related(
        "assessment", "assessment__subject", "assessment__unit", "assessment__lesson",
        "dynamic_subject",
    )
    if subject_id:
        query = query.filter(Q(assessment__subject_id=subject_id) | Q(dynamic_subject_id=subject_id))
    if category == "ministerial":
        query = query.filter(
            dynamic_assessment_type="",
            assessment__assessment_type__in=(
                AssessmentType.MINISTERIAL_EXAM,
                AssessmentType.LESSON_MINISTERIAL,
            ),
        )
    elif category == "other":
        query = query.filter(
            Q(dynamic_assessment_type__gt="")
            | Q(assessment__isnull=True)
            | ~Q(assessment__assessment_type__in=(
                AssessmentType.MINISTERIAL_EXAM,
                AssessmentType.LESSON_MINISTERIAL,
            ))
        )
    return query.order_by("-submitted_at", "-created_at")
