import logging
from typing import Dict, Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services.merge_service import register_merge_handler
from apps.curriculum.models import StudyEnrollment
from apps.subscriptions.models import (
    ActivationCodeUsage,
    Subscription,
    SubscriptionAudit,
    SubscriptionSource,
    SubscriptionStatus,
)
from apps.entitlements.models import UserEntitlement

logger = logging.getLogger("subscriptions.merge")


def subscription_merge_handler(source_guest: User, target_user: User) -> Dict[str, Any] | None:
    """
    Merges subscriptions, activation code usages, and user entitlements
    from source_guest to target_user.
    """
    guest_subs = list(Subscription.objects.filter(user=source_guest).select_for_update())
    guest_usages = list(ActivationCodeUsage.objects.filter(user=source_guest).select_for_update())
    guest_user_ents = list(UserEntitlement.objects.filter(user=source_guest).select_for_update())

    if not guest_subs and not guest_usages and not guest_user_ents:
        return None

    target_enrollment = StudyEnrollment.objects.filter(user=target_user, is_active=True).first()

    subs_reassigned = 0
    usages_reassigned = 0
    entitlements_reassigned = 0

    now = timezone.now()

    with transaction.atomic():
        # 1. Re-assign subscriptions
        for sub in guest_subs:
            # Preserve one coherent active subscription per academic-year
            # context. Merging must never stack durations beyond year end.
            if target_enrollment and sub.status == SubscriptionStatus.ACTIVE and sub.expires_at > now:
                target_sub = Subscription.objects.filter(
                    user=target_user,
                    study_enrollment=target_enrollment,
                    academic_year_id=sub.academic_year_id,
                    status=SubscriptionStatus.ACTIVE,
                    expires_at__gt=now,
                ).prefetch_related("selected_subjects").first()

                if target_sub:
                    before = {
                        "plan_id": str(target_sub.plan_id),
                        "subject_ids": sorted(str(item.id) for item in target_sub.selected_subjects.all()),
                        "is_all_subjects": target_sub.is_all_subjects,
                        "expires_at": target_sub.expires_at.isoformat(),
                    }
                    subject_ids = set(target_sub.selected_subjects.values_list("id", flat=True))
                    subject_ids.update(sub.selected_subjects.values_list("id", flat=True))
                    target_sub.is_all_subjects = target_sub.is_all_subjects or sub.is_all_subjects
                    target_sub.expires_at = max(target_sub.expires_at, sub.expires_at)
                    if target_sub.academic_year_id:
                        target_sub.expires_at = min(
                            target_sub.expires_at,
                            target_sub.academic_year.ends_at,
                        )
                    target_sub.save(update_fields=["is_all_subjects", "expires_at", "updated_at"])
                    if not target_sub.is_all_subjects:
                        target_sub.selected_subjects.add(*subject_ids)
                    SubscriptionAudit.objects.create(
                        subscription=target_sub,
                        action="guest_account_merge",
                        source=SubscriptionSource.LEGACY_GUEST,
                        actor=target_user,
                        reason="guest_to_registered_account_merge",
                        before_state=before,
                        after_state={
                            "plan_id": str(target_sub.plan_id),
                            "subject_ids": sorted(str(value) for value in subject_ids),
                            "is_all_subjects": target_sub.is_all_subjects,
                            "expires_at": target_sub.expires_at.isoformat(),
                        },
                    )

                    # Deactivate/cancel original guest sub
                    sub.status = SubscriptionStatus.CANCELLED
                    sub.user = target_user
                    sub.study_enrollment = target_enrollment
                    sub.save(update_fields=["status", "user", "study_enrollment", "updated_at"])
                    subs_reassigned += 1
                    continue

            sub.user = target_user
            if target_enrollment:
                sub.study_enrollment = target_enrollment
            sub.save(update_fields=["user", "study_enrollment", "updated_at"])
            subs_reassigned += 1

        # 2. Re-assign Usages
        for usage in guest_usages:
            usage.user = target_user
            if target_enrollment:
                usage.study_enrollment = target_enrollment
            usage.save(update_fields=["user", "study_enrollment"])
            usages_reassigned += 1

        # 3. Re-assign UserEntitlements
        for u_ent in guest_user_ents:
            u_ent.user = target_user
            if target_enrollment:
                u_ent.study_enrollment = target_enrollment
            u_ent.save(update_fields=["user", "study_enrollment", "updated_at"])
            entitlements_reassigned += 1

    logger.info("Successfully merged guest subscriptions for guest_id=%s into user_id=%s",
                source_guest.id, target_user.id)

    return {
        "subscriptions_reassigned": subs_reassigned,
        "usages_reassigned": usages_reassigned,
        "entitlements_reassigned": entitlements_reassigned,
    }


# Automatically register merge handler
register_merge_handler(subscription_merge_handler)
