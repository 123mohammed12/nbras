"""
Account Merge Service.

Implements transactional, idempotent merging of guest accounts into registered user accounts.
Includes an extensible Merge Handler Registry for future modules (exams, progress, bookmarks).
"""

import logging
from typing import Callable, List

from django.db import transaction
from django.utils import timezone

from apps.accounts.exceptions import MergeFailedError, MergeInProgressError
from apps.accounts.models import AccountMerge, User, UserDevice, UserSession
from apps.accounts.services.session_service import (
    create_user_session,
    revoke_all_sessions,
)
from apps.progress.services.guest_merge import progress_merge_handler
from apps.analytics.services.guest_merge import analytics_merge_handler
from apps.synchronization.services.guest_merge import sync_merge_handler

logger = logging.getLogger("accounts.merge")

# Type definition for merge handler functions
MergeHandler = Callable[[User, User], dict | None]

# Global registry for merge handlers
MERGE_HANDLERS: List[MergeHandler] = []


def register_merge_handler(handler: MergeHandler):
    """
    Register a callback function to handle merging specific domain data.
    Signature: handler(source_guest: User, target_user: User) -> dict | None
    """
    if handler not in MERGE_HANDLERS:
        MERGE_HANDLERS.append(handler)
    return handler


# Default Merge Handler for Devices & Sessions
def default_devices_merge_handler(source_guest: User, target_user: User) -> dict:
    """
    Re-assign devices from source guest to target user.
    """
    devices_reassigned = 0
    for device in source_guest.devices.select_for_update().all():
        # If target user already has this installation_id, deactivate source device
        existing = UserDevice.objects.filter(
            user=target_user,
            installation_id=device.installation_id,
        ).first()
        if existing:
            device.is_active = False
            device.save(update_fields=["is_active"])
        else:
            device.user = target_user
            device.save(update_fields=["user"])
            devices_reassigned += 1

    return {"devices_reassigned": devices_reassigned}


# StudentProfile Merge Handler
def student_profile_merge_handler(source_guest: User, target_user: User) -> dict | None:
    """
    Merge StudentProfile from source_guest to target_user.

    1. If target_user has no profile and source_guest has a profile: transfer it.
    2. If target_user has a profile and source_guest has a profile:
       - Fill missing location/name fields on target profile from guest profile.
       - Do not overwrite confirmed target values.
       - Delete redundant guest profile.
    """
    from apps.accounts.models.student_profile import StudentProfile

    guest_profile = StudentProfile.objects.filter(user=source_guest).first()
    if not guest_profile:
        return None

    target_profile = StudentProfile.objects.filter(user=target_user).first()

    if not target_profile:
        # Target has no profile -> transfer guest profile directly
        guest_profile.user = target_user
        guest_profile.save(update_fields=["user", "updated_at"])
        return {"profile_transferred": True}

    # Both profiles exist -> fill missing fields on target profile
    populated_fields = []
    fields_to_check = [
        "full_name", "governorate", "district", "isolation", "school",
        "custom_governorate_name", "custom_district_name",
        "custom_isolation_name", "custom_school_name",
    ]

    for field in fields_to_check:
        target_val = getattr(target_profile, field)
        guest_val = getattr(guest_profile, field)
        if not target_val and guest_val:
            setattr(target_profile, field, guest_val)
            populated_fields.append(field)

    if populated_fields:
        target_profile.save(update_fields=populated_fields + ["updated_at"])

    # Delete redundant guest profile
    guest_profile.delete()

    return {"profile_merged": True, "fields_populated": populated_fields}


# Register default handlers
register_merge_handler(default_devices_merge_handler)
register_merge_handler(student_profile_merge_handler)
register_merge_handler(progress_merge_handler)
register_merge_handler(analytics_merge_handler)
register_merge_handler(sync_merge_handler)


@transaction.atomic
def merge_guest_account(
    source_guest: User,
    target_user: User,
    device_data: dict | None = None,
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[AccountMerge, dict]:
    """
    Merge source_guest into target_user.

    1. Idempotent & Lock check via AccountMerge.
    2. Runs all registered merge handlers.
    3. Revokes source_guest sessions.
    4. Deactivates source_guest account.
    5. Issues new target_user session.
    """
    if source_guest.id == target_user.id:
        raise ValueError("Cannot merge a user into themselves.")

    # Lock both users to prevent concurrent modifications
    locked_users = list(
        User.objects.select_for_update().filter(
            id__in=[source_guest.id, target_user.id]
        ).order_by("id")
    )
    if len(locked_users) != 2:
        raise MergeFailedError("تعذر العثور على الحسابات المطلوبة للدمج.")

    # Refresh references from locked queryset
    for u in locked_users:
        if u.id == source_guest.id:
            source_guest = u
        elif u.id == target_user.id:
            target_user = u

    # Check for existing in-progress merge
    existing = AccountMerge.objects.select_for_update().filter(
        source_guest=source_guest,
        target_user=target_user,
        status__in=[AccountMerge.Status.PENDING, AccountMerge.Status.PROCESSING],
    ).first()

    if existing:
        raise MergeInProgressError()

    # Check if already completed (idempotent)
    completed = AccountMerge.objects.filter(
        source_guest=source_guest,
        target_user=target_user,
        status=AccountMerge.Status.COMPLETED,
    ).first()

    if completed:
        # Idempotent return
        device = None
        if device_data and device_data.get("installation_id"):
            device = UserDevice.objects.filter(
                user=target_user, installation_id=device_data["installation_id"]
            ).first()
        tokens = create_user_session(user=target_user, device=device, request_ip=request_ip, user_agent=user_agent)
        return completed, tokens

    merge_record = AccountMerge.objects.create(
        source_guest=source_guest,
        target_user=target_user,
        status=AccountMerge.Status.PROCESSING,
        started_at=timezone.now(),
    )

    try:
        conflicts_and_results = {}
        for handler in MERGE_HANDLERS:
            result = handler(source_guest, target_user)
            if result:
                handler_name = handler.__name__
                conflicts_and_results[handler_name] = result

        # Deactivate guest user & revoke guest sessions
        revoke_all_sessions(source_guest)
        source_guest.is_active = False
        source_guest.save(update_fields=["is_active"])

        merge_record.status = AccountMerge.Status.COMPLETED
        merge_record.completed_at = timezone.now()
        merge_record.conflict_data = conflicts_and_results
        merge_record.save(update_fields=["status", "completed_at", "conflict_data", "updated_at"])

        # Create session for target user
        device = None
        if device_data and device_data.get("installation_id"):
            device = UserDevice.objects.filter(
                user=target_user, installation_id=device_data["installation_id"]
            ).first()
        tokens = create_user_session(
            user=target_user,
            device=device,
            request_ip=request_ip,
            user_agent=user_agent,
        )

        return merge_record, tokens

    except Exception as e:
        logger.exception("Account merge failed: %s", str(e))
        merge_record.status = AccountMerge.Status.FAILED
        merge_record.error_message = str(e)
        merge_record.save(update_fields=["status", "error_message", "updated_at"])
        raise MergeFailedError(f"فشلت عملية الدمج: {str(e)}")
