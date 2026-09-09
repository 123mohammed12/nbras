"""
StudyEnrollment Account Merge Handler.

Transfers guest study enrollments to registered target user upon account merge.
Registered with apps.accounts.services.merge_service.MERGE_HANDLERS.
"""

import logging
from django.db import transaction
from apps.accounts.services.merge_service import register_merge_handler
from apps.curriculum.models import StudyEnrollment

logger = logging.getLogger("curriculum.merge")


def curriculum_enrollment_merge_handler(source_guest, target_user) -> dict:
    """
    Handle merging StudyEnrollment records from source_guest into target_user.

    1. If target_user has no active enrollment, transfer source_guest's active enrollment to target_user.
    2. If target_user already has an active enrollment, reassign guest's active enrollment to target_user
       as a historical record (is_active=False, status=CHANGED).
    3. Reassign all inactive/historical guest enrollments to target_user.
    """
    with transaction.atomic():
        target_active = (
            StudyEnrollment.objects.select_for_update(of=("self",))
            .filter(user=target_user, is_active=True)
            .first()
        )

        guest_enrollments = list(
            StudyEnrollment.objects.select_for_update(of=("self",))
            .filter(user=source_guest)
        )

        reassigned_count = 0

        for enr in guest_enrollments:
            if enr.is_active:
                if target_active:
                    # Target already has active enrollment -> mark guest's as historical
                    enr.user = target_user
                    enr.is_active = False
                    enr.status = StudyEnrollment.Status.CHANGED
                    enr.save(update_fields=["user", "is_active", "status", "updated_at"])
                else:
                    # Target has no active enrollment -> make guest's enrollment active for target
                    enr.user = target_user
                    enr.save(update_fields=["user", "updated_at"])
                    target_active = enr
            else:
                # Reassign historical enrollment
                enr.user = target_user
                enr.save(update_fields=["user", "updated_at"])

            reassigned_count += 1

        logger.info(
            "Merged %d StudyEnrollment records from guest %s to user %s",
            reassigned_count,
            source_guest.id,
            target_user.id,
        )

        return {"enrollments_reassigned": reassigned_count}


# Register the handler
register_merge_handler(curriculum_enrollment_merge_handler)
