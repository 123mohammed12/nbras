import secrets

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import ApplicationError
from apps.subscriptions.models import (
    ActivationCode,
    ActivationCodeBatch,
    ActivationCodeHashVersion,
    ActivationCodeStatus,
)
from apps.subscriptions.services.code_service import hash_activation_code


ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _raw_code():
    value = "".join(secrets.choice(ALPHABET) for _ in range(16))
    return f"{value[:4]}-{value[4:8]}-{value[8:12]}-{value[12:]}"


def _masked(raw_code):
    parts = raw_code.split("-")
    return f"{parts[0]}-{parts[1]}-****-{parts[3]}"


@transaction.atomic
def generate_activation_code_batch(
    *, plan, quantity, actor=None, batch_code="", code_expires_at=None,
):
    if not plan.is_active:
        raise ApplicationError("لا يمكن إنشاء رموز لباقة غير نشطة.", code="PLAN_INACTIVE")
    if quantity < 1 or quantity > 5000:
        raise ApplicationError("يجب أن تكون الكمية بين 1 و 5000.", code="INVALID_BATCH_QUANTITY")
    now = timezone.now()
    if code_expires_at and code_expires_at <= now:
        raise ApplicationError("يجب أن يكون انتهاء الرموز في المستقبل.", code="INVALID_CODE_EXPIRY")
    batch_code = batch_code.strip() or f"{plan.code}-{now:%Y%m%d%H%M%S}-{secrets.token_hex(2).upper()}"
    if ActivationCodeBatch.objects.filter(batch_code=batch_code).exists():
        raise ApplicationError("معرف الدفعة مستخدم بالفعل.", code="BATCH_CODE_EXISTS")

    batch = ActivationCodeBatch.objects.create(
        batch_code=batch_code,
        plan=plan,
        quantity=quantity,
        code_expires_at=code_expires_at,
        created_by=actor,
    )
    raw_codes = []
    rows = []
    for _ in range(quantity):
        for _attempt in range(10):
            raw = _raw_code()
            digest = hash_activation_code(raw)
            if not ActivationCode.objects.filter(code_hash=digest).exists():
                break
        else:
            raise ApplicationError("تعذر إنشاء رمز فريد.", code="CODE_GENERATION_FAILED")
        raw_codes.append(raw)
        rows.append(
            ActivationCode(
                code_hash=digest,
                hash_version=ActivationCodeHashVersion.HMAC_SHA256_V1,
                display_code_masked=_masked(raw),
                plan=plan,
                batch=batch,
                max_uses=1,
                used_count=0,
                starts_at=now,
                expires_at=code_expires_at,
                status=ActivationCodeStatus.AVAILABLE,
                batch_code=batch_code,
                created_by=actor,
            )
        )
    ActivationCode.objects.bulk_create(rows)
    return batch, raw_codes


@transaction.atomic
def revoke_activation_code_batch(*, batch: ActivationCodeBatch, actor=None, reason=""):
    """
    Safely revoke all available activation codes in a batch.
    Only codes in AVAILABLE status are transitioned to REVOKED.
    Redeemed or already revoked codes remain unaffected.
    """
    if not actor or not actor.is_superuser:
        raise ApplicationError("إلغاء دفعات الرموز يتطلب صلاحية مدير النظام.", code="SUPERUSER_REQUIRED", status_code=403)

    available_codes = batch.codes.filter(status=ActivationCodeStatus.AVAILABLE)
    revoked_count = available_codes.update(status=ActivationCodeStatus.REVOKED)
    return revoked_count

