import hmac
import hashlib
from typing import Tuple
from django.conf import settings

from apps.subscriptions.models import ActivationCode, ActivationCodeHashVersion


def hash_activation_code(raw_code: str) -> str:
    """
    Computes HMAC-SHA256 hash for raw activation code using ACTIVATION_CODE_HMAC_SECRET.
    """
    clean_code = raw_code.strip().upper()
    secret = getattr(settings, "ACTIVATION_CODE_HMAC_SECRET", "INSECURE-DEV-ACTIVATION-HMAC-SECRET-CHANGE-IN-PRODUCTION")
    return hmac.new(
        secret.encode("utf-8"),
        clean_code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_legacy_code(raw_code: str) -> str:
    """
    Computes plain SHA256 hash for legacy activation codes.
    """
    clean_code = raw_code.strip().upper()
    return hashlib.sha256(clean_code.encode("utf-8")).hexdigest()


def find_activation_code_by_raw_code(raw_code: str) -> Tuple[ActivationCode | None, str | None]:
    """
    Looks up an ActivationCode by computing HMAC-SHA256 (or fallback legacy SHA-256).
    Returns (code_obj, matched_version).
    """
    if not raw_code:
        return None, None

    # 1. Try HMAC-SHA256 (v1)
    hmac_hash = hash_activation_code(raw_code)
    code_obj = ActivationCode.objects.filter(
        code_hash=hmac_hash,
        hash_version=ActivationCodeHashVersion.HMAC_SHA256_V1,
    ).select_for_update().first()

    if code_obj:
        return code_obj, ActivationCodeHashVersion.HMAC_SHA256_V1

    # 2. Try Legacy SHA-256 fallback
    legacy_hash = hash_legacy_code(raw_code)
    legacy_code = ActivationCode.objects.filter(
        code_hash=legacy_hash,
        hash_version=ActivationCodeHashVersion.LEGACY_SHA256,
    ).select_for_update().first()

    if legacy_code:
        return legacy_code, ActivationCodeHashVersion.LEGACY_SHA256

    return None, None
