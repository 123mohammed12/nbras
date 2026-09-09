import logging

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import ApplicationError
from apps.subscriptions.models import (
    ActivationCodeStatus, ActivationCodeUsage, SubscriptionSource,
)
from apps.subscriptions.services.code_service import find_activation_code_by_raw_code
from apps.subscriptions.services.subscription_service import (
    grant_subscription_access, preview_subscription_grant,
)

logger = logging.getLogger("subscriptions.redeem")


def _validate_actor(user, enrollment):
    if getattr(user, "is_guest", False):
        raise ApplicationError("سجّل الدخول أو أنشئ حساباً أولاً لتفعيل الباقة.", code="GUEST_REDEEM_NOT_ALLOWED", status_code=403)
    if not enrollment or not enrollment.is_active or enrollment.user_id != user.id:
        raise ApplicationError("لا يوجد ملف دراسي نشط صالح.", code="NO_ACTIVE_ENROLLMENT")


def _validate_code(code):
    now = timezone.now()
    if not code or code.status not in {ActivationCodeStatus.AVAILABLE, ActivationCodeStatus.ACTIVE}:
        raise ApplicationError("رمز التفعيل غير صالح أو غير متاح.", code="INVALID_ACTIVATION_CODE")
    if code.starts_at and code.starts_at > now:
        raise ApplicationError("رمز التفعيل غير صالح أو غير متاح.", code="INVALID_ACTIVATION_CODE")
    if code.expires_at and code.expires_at <= now:
        code.status = ActivationCodeStatus.EXPIRED
        code.save(update_fields=["status", "updated_at"])
        raise ApplicationError("رمز التفعيل غير صالح أو غير متاح.", code="INVALID_ACTIVATION_CODE")
    if code.used_count or code.usages.exists():
        raise ApplicationError("رمز التفعيل غير صالح أو غير متاح.", code="INVALID_ACTIVATION_CODE")
    if not code.plan.is_active:
        raise ApplicationError("رمز التفعيل غير صالح أو غير متاح.", code="INVALID_ACTIVATION_CODE")


@transaction.atomic
def preview_activation_code(*, user, enrollment, raw_code, selected_subject_ids=None):
    _validate_actor(user, enrollment)
    code, _ = find_activation_code_by_raw_code(raw_code)
    _validate_code(code)
    preview = preview_subscription_grant(
        user=user, enrollment=enrollment, plan=code.plan,
        selected_subject_ids=selected_subject_ids,
        allow_incomplete=not bool(selected_subject_ids),
    )
    return {**preview, "code_masked": code.display_code_masked}


@transaction.atomic
def redeem_activation_code(
    *, user, enrollment, raw_code, selected_subject_ids=None,
    idempotency_key=None, request_id=None,
):
    _validate_actor(user, enrollment)
    if idempotency_key:
        existing = ActivationCodeUsage.objects.filter(
            user=user, idempotency_key=idempotency_key,
        ).select_related("subscription", "subscription__plan").first()
        if existing and existing.subscription:
            return existing.subscription, {
                "message": "تمت معالجة طلب التفعيل مسبقاً.",
                "idempotent_replayed": True,
            }

    code, _ = find_activation_code_by_raw_code(raw_code)
    if idempotency_key:
        # A concurrent request with the same key may have committed while this
        # transaction waited for the activation-code row lock.
        existing = ActivationCodeUsage.objects.filter(
            user=user, idempotency_key=idempotency_key,
        ).select_related("subscription", "subscription__plan").first()
        if existing and existing.subscription:
            return existing.subscription, {
                "message": "تمت معالجة طلب التفعيل مسبقاً.",
                "idempotent_replayed": True,
            }
    _validate_code(code)
    # Preview is repeated under the same row lock; invalid/no-benefit grants
    # fail before the credential is consumed.
    preview_subscription_grant(
        user=user, enrollment=enrollment, plan=code.plan,
        selected_subject_ids=selected_subject_ids,
    )
    usage = ActivationCodeUsage.objects.create(
        activation_code=code, user=user, study_enrollment=enrollment,
        request_id=request_id, idempotency_key=idempotency_key,
    )
    subscription, _ = grant_subscription_access(
        user=user, enrollment=enrollment, plan=code.plan,
        selected_subject_ids=selected_subject_ids,
        source=SubscriptionSource.CODE, actor=user, usage=usage,
        reason="activation_code",
    )
    usage.subscription = subscription
    usage.save(update_fields=["subscription"])
    code.used_count = 1
    code.status = (
        ActivationCodeStatus.EXHAUSTED
        if code.status == ActivationCodeStatus.ACTIVE
        else ActivationCodeStatus.REDEEMED
    )
    code.save(update_fields=["used_count", "status", "updated_at"])
    logger.info("Activation code id=%s redeemed by user_id=%s", code.id, user.id)
    return subscription, {
        "message": "تم تفعيل الباقة بنجاح.",
        "idempotent_replayed": False,
    }
