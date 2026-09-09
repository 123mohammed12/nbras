import logging
from typing import Dict, Any, List, Optional
from django.conf import settings
from apps.curriculum.models import StudyEnrollment, Subject, Unit, Lesson
from apps.content.models import Summary, FlashcardDeck, ContentLink
from apps.entitlements.services.access_service import check_resource_access
from apps.synchronization.models import SyncChange, SyncChangeAction
from apps.synchronization.services.cursor_service import (
    generate_server_cursor,
    parse_and_validate_cursor,
    calculate_access_revision,
)

logger = logging.getLogger("synchronization.manifest")


def build_full_manifest(
    *,
    user,
    enrollment: Optional[StudyEnrollment],
    page: int = 1,
    page_size: int = 100,
    snapshot_sequence: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Builds a Full Manifest for the user's active enrollment.
    Efficiently fetches resources and evaluates access decisions in batch.

    Snapshot Stability:
      - On first page request (snapshot_sequence=None), captures upper_sequence.
      - On subsequent pages, caller passes snapshot_sequence from cursor to
        ensure the same snapshot bound across all pages.
    """
    page_size = min(page_size, getattr(settings, "SYNC_MANIFEST_MAX_PAGE_SIZE", 200))
    access_rev = calculate_access_revision(user, enrollment)

    # 1. Capture upper_sequence once for snapshot stability
    if snapshot_sequence is not None:
        upper_sequence = snapshot_sequence
    else:
        latest_change = SyncChange.objects.order_by("-sequence").first()
        upper_sequence = latest_change.sequence if latest_change else 0

    # 2. Fetch Subjects / Units / Lessons for the enrollment's grade
    if enrollment and enrollment.grade:
        lessons_qs = Lesson.objects.filter(
            unit__subject__grade=enrollment.grade,
            status="published",
        ).select_related("unit", "unit__subject").order_by("unit__subject__sort_order", "unit__sort_order", "sort_order")
    else:
        lessons_qs = Lesson.objects.filter(
            status="published",
        ).select_related("unit", "unit__subject").order_by("sort_order")

    total_count = lessons_qs.count()
    start_offset = (page - 1) * page_size
    end_offset = start_offset + page_size
    page_lessons = list(lessons_qs[start_offset:end_offset])

    items = []

    for lesson in page_lessons:
        resource_id = str(lesson.id)
        resource_type = "lesson"

        decision = check_resource_access(
            user=user,
            enrollment=enrollment,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        is_locked = not decision.allowed

        item_data = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "title": lesson.title,
            "subject_id": str(lesson.unit.subject_id) if lesson.unit else None,
            "unit_id": str(lesson.unit_id) if lesson else None,
            "order": getattr(lesson, "sort_order", 0),
            "is_locked": is_locked,
            "is_free_preview": getattr(lesson, "is_free_preview", False),
            "resource_version": str(getattr(lesson, "version", 1)),
            "updated_at": lesson.updated_at.isoformat() if hasattr(lesson, "updated_at") and lesson.updated_at else None,
            "download_available": not is_locked,
            "protected_resource_type": resource_type,
            "protected_resource_id": resource_id,
        }

        if is_locked:
            item_data["download_available"] = False

        items.append(item_data)

    has_next = end_offset < total_count
    next_page_cursor = None

    if has_next:
        next_page_cursor = generate_server_cursor(
            user=user,
            enrollment=enrollment,
            last_sequence=upper_sequence,
        )

    delta_cursor = generate_server_cursor(
        user=user,
        enrollment=enrollment,
        last_sequence=upper_sequence,
    )

    return {
        "schema_version": "1",
        "mode": "full",
        "cursor": delta_cursor,
        "next_page_cursor": next_page_cursor,
        "access_revision": access_rev,
        "upper_sequence": upper_sequence,
        "page": page,
        "page_size": page_size,
        "total_items": total_count,
        "items": items,
        "tombstones": [],
    }


def build_delta_manifest(
    *,
    user,
    enrollment: Optional[StudyEnrollment],
    cursor_str: str,
) -> Dict[str, Any]:
    """
    Builds a Delta Manifest returning changes since last_sequence in cursor.
    """
    payload, reset_required = parse_and_validate_cursor(
        cursor_str,
        user=user,
        enrollment=enrollment,
    )

    access_rev = calculate_access_revision(user, enrollment)

    if reset_required:
        return {
            "schema_version": "1",
            "mode": "delta",
            "reset_required": True,
            "reason": "ACCESS_SCOPE_CHANGED",
            "access_revision": access_rev,
            "items": [],
            "tombstones": [],
        }

    last_sequence = payload.get("last_sequence", 0)

    changes_qs = SyncChange.objects.filter(sequence__gt=last_sequence).order_by("sequence")[:100]
    changes = list(changes_qs)

    items = []
    tombstones = []
    new_max_seq = last_sequence

    for change in changes:
        new_max_seq = max(new_max_seq, change.sequence)
        if change.action in [SyncChangeAction.DELETE, SyncChangeAction.ARCHIVE, SyncChangeAction.ACCESS_REVOKED]:
            tombstones.append({
                "resource_type": change.resource_type,
                "resource_id": change.resource_id,
                "action": change.action,
                "sequence": change.sequence,
                "occurred_at": change.changed_at.isoformat(),
            })
        else:
            items.append({
                "resource_type": change.resource_type,
                "resource_id": change.resource_id,
                "action": change.action,
                "resource_version": change.resource_version,
                "sequence": change.sequence,
                "metadata": change.metadata_snapshot,
            })

    new_cursor = generate_server_cursor(
        user=user,
        enrollment=enrollment,
        last_sequence=new_max_seq,
    )

    return {
        "schema_version": "1",
        "mode": "delta",
        "reset_required": False,
        "cursor": new_cursor,
        "access_revision": access_rev,
        "items": items,
        "tombstones": tombstones,
    }
