from django.db.models import Count, Q
from django.utils import timezone

from apps.curriculum.models import (
    ContentStatus,
    DashboardBanner,
    Lesson,
    StudyEnrollment,
    Subject,
    Unit,
)
from apps.curriculum.selectors.curriculum_selectors import get_user_subjects
from apps.entitlements.services.access_service import (
    AccessContext,
    check_resources_access_batch,
)
from apps.progress.models import LessonProgress, SubjectProgress, UnitProgress
from apps.progress.services.progress_selectors import (
    calculate_accessible_completion_for_subjects,
)


_ACTIVE_PROGRESS_STATUSES = ("in_progress", "needs_review")


def _progress_candidates(user, enrollment):
    lesson_progress = list(
        LessonProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            status__in=_ACTIVE_PROGRESS_STATUSES,
            lesson__status=ContentStatus.PUBLISHED,
            lesson__unit__status=ContentStatus.PUBLISHED,
            lesson__unit__subject__status=ContentStatus.PUBLISHED,
        )
        .select_related("lesson__unit__subject")
        .order_by("-last_activity_at")[:10]
    )
    unit_progress = list(
        UnitProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            status__in=_ACTIVE_PROGRESS_STATUSES,
            unit__status=ContentStatus.PUBLISHED,
            unit__subject__status=ContentStatus.PUBLISHED,
        )
        .select_related("unit__subject")
        .order_by("-last_activity_at")[:10]
    )
    subject_progress = list(
        SubjectProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            status__in=_ACTIVE_PROGRESS_STATUSES,
            subject__status=ContentStatus.PUBLISHED,
        )
        .select_related("subject")
        .order_by("-last_activity_at")[:10]
    )

    candidates = []
    for progress in lesson_progress:
        candidates.append(
            {
                "resource_type": "lesson",
                "resource_id": str(progress.lesson_id),
                "progress": progress,
                "subject": progress.lesson.unit.subject,
                "unit": progress.lesson.unit,
                "lesson": progress.lesson,
            }
        )
    for progress in unit_progress:
        candidates.append(
            {
                "resource_type": "unit",
                "resource_id": str(progress.unit_id),
                "progress": progress,
                "subject": progress.unit.subject,
                "unit": progress.unit,
                "lesson": None,
            }
        )
    for progress in subject_progress:
        candidates.append(
            {
                "resource_type": "subject",
                "resource_id": str(progress.subject_id),
                "progress": progress,
                "subject": progress.subject,
                "unit": None,
                "lesson": None,
            }
        )
    return sorted(
        candidates,
        key=lambda item: item["progress"].last_activity_at,
        reverse=True,
    )


def _get_continue_learning(user, enrollment, context):
    from apps.progress.services.aggregation import resolve_continue_item

    item = resolve_continue_item(
        user=user,
        enrollment=enrollment,
        context=context,
    )
    if not item:
        return None
    subject = Subject.objects.filter(id=item.get("subject_id")).first()
    if subject is None:
        return None
    unit = Unit.objects.filter(id=item.get("unit_id")).first() if item.get("unit_id") else None
    lesson = Lesson.objects.filter(id=item.get("lesson_id")).first() if item.get("lesson_id") else None
    return {
        "target_type": item["type"],
        "target_id": item.get("attempt_id") or item["resource_id"],
        "subject_id": str(item.get("subject_id")),
        "subject_name": subject.name_ar,
        "unit_id": item.get("unit_id"),
        "unit_title": unit.title if unit else None,
        "lesson_id": item.get("lesson_id"),
        "lesson_title": lesson.title if lesson else None,
        "completion_percentage": float(item.get("progress") or 0),
        "last_activity_at": item["last_activity_at"],
    }


def get_curriculum_dashboard(user):
    enrollment = (
        StudyEnrollment.objects.filter(user=user, is_active=True)
        .select_related("grade", "section")
        .first()
    )
    if enrollment is None:
        return None

    subjects = list(
        get_user_subjects(
            grade_id=str(enrollment.grade_id),
            section_id=str(enrollment.section_id),
        ).annotate(
            published_units_count=Count(
                "units",
                filter=Q(units__status=ContentStatus.PUBLISHED),
                distinct=True,
            ),
            published_lessons_count=Count(
                "units__lessons",
                filter=Q(
                    units__status=ContentStatus.PUBLISHED,
                    units__lessons__status=ContentStatus.PUBLISHED,
                ),
                distinct=True,
            ),
        )
    )

    context = AccessContext.build(user=user, enrollment=enrollment)
    subject_resources = [
        {"type": "subject", "id": str(subject.id)} for subject in subjects
    ]
    access_map = check_resources_access_batch(
        user=user,
        enrollment=enrollment,
        resources=subject_resources,
        context=context,
    )
    progress_rows = SubjectProgress.objects.filter(
        user=user,
        study_enrollment=enrollment,
        subject_id__in=[subject.id for subject in subjects],
    ).select_related("subject")
    progress_map = {str(row.subject_id): row for row in progress_rows}
    progressed_subjects = [
        subject for subject in subjects if str(subject.id) in progress_map
    ]
    accessible_map = calculate_accessible_completion_for_subjects(
        user,
        enrollment,
        progressed_subjects,
        context=context,
    )
    free_subject_ids = {
        str(policy.subject_id)
        for policy in context.free_access_policies
        if policy.subject_id and policy.free_unit_id
    }

    subject_items = []
    for subject in subjects:
        subject_id = str(subject.id)
        decision = access_map.get(("subject", subject_id))
        progress = progress_map.get(subject_id)
        has_free_content = subject_id in free_subject_ids
        allowed = bool(decision and decision.allowed)
        subject_items.append(
            {
                "id": subject_id,
                "name_ar": subject.name_ar,
                "description": subject.description,
                "icon_path": subject.icon_path.url if subject.icon_path else None,
                "cover_image_path": (
                    subject.cover_image_path.url if subject.cover_image_path else None
                ),
                "published_units_count": subject.published_units_count,
                "published_lessons_count": subject.published_lessons_count,
                "has_free_content": has_free_content,
                "access_status": (
                    "unlocked" if allowed else "partial" if has_free_content else "locked"
                ),
                "access": decision.to_dict() if decision else None,
                "progress": (
                    {
                        "status": progress.status,
                        "completion_percentage": float(progress.completion_percentage),
                        "accessible_completion_percentage": accessible_map.get(subject_id),
                        "last_activity_at": progress.last_activity_at,
                    }
                    if progress
                    else None
                ),
            }
        )

    active_subscription = context.active_subscriptions[0] if context.active_subscriptions else None
    has_restricted_content = any(item["access_status"] != "unlocked" for item in subject_items)

    now = timezone.now()
    banner_filter = (
        Q(is_active=True)
        & (Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        & (Q(ends_at__isnull=True) | Q(ends_at__gte=now))
        & (Q(grade__isnull=True) | Q(grade_id=enrollment.grade_id))
        & (Q(section__isnull=True) | Q(section_id=enrollment.section_id))
    )
    if enrollment.academic_year_id:
        banner_filter &= (
            Q(academic_year__isnull=True)
            | Q(academic_year_id=enrollment.academic_year_id)
        )

    banner_rows = list(
        DashboardBanner.objects.filter(banner_filter).order_by("sort_order", "-created_at")
    )
    carousel_items = [
        {
            "id": str(banner.id),
            "type": banner.item_type,
            "title": banner.title,
            "subtitle": banner.subtitle,
            "image_url": banner.image_path.url if banner.image_path else None,
            "badge": banner.badge_text or None,
            "cta_label": banner.cta_label or None,
            "cta_type": banner.cta_type,
            "target_id": banner.target_id or None,
            "sort_order": banner.sort_order,
        }
        for banner in banner_rows
    ]

    return {
        "enrollment": enrollment,
        "subjects": subject_items,
        "continue_learning": _get_continue_learning(user, enrollment, context),
        "subscription": {
            "has_active_access": active_subscription is not None or context.is_staff,
            "show_offer": not context.is_staff
            and active_subscription is None
            and has_restricted_content,
            "active_plan_name": active_subscription.plan.name if active_subscription else None,
        },
        "carousel_items": carousel_items,
    }
