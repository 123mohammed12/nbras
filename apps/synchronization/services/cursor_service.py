import hashlib
import time
import logging
from typing import Dict, Any, Tuple
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.conf import settings
from apps.entitlements.models import UserEntitlement
from apps.subscriptions.models import Subscription
from apps.curriculum.models import StudyEnrollment

logger = logging.getLogger("synchronization.cursor")

CURSOR_SALT = "apps.synchronization.cursor_v1"
CURSOR_MAX_AGE_SECONDS = 86400 * 30  # 30 days


def calculate_access_revision(user, enrollment) -> str:
    """
    Computes a deterministic access revision hash for the given user and enrollment based on:
    - Active UserEntitlements
    - Active Subscriptions
    - Enrollment ID and grade
    """
    entitlements_str = ""
    if user and user.is_authenticated:
        u_ents = list(
            UserEntitlement.objects.filter(user=user, is_active=True)
            .values_list("id", "updated_at")
            .order_by("id")
        )
        subs = list(
            Subscription.objects.filter(user=user, status="active")
            .values_list("id", "updated_at")
            .order_by("id")
        )
        entitlements_str += f"{u_ents}:{subs}"

    enrollment_str = f"{enrollment.id}:{enrollment.grade_id}:{enrollment.section_id}" if enrollment else "guest"
    raw_str = f"{entitlements_str}|{enrollment_str}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


def generate_server_cursor(
    *,
    user,
    enrollment,
    last_sequence: int,
    schema_version: str = "1",
) -> str:
    """
    Generates an opaque, server-signed cursor.
    """
    signer = TimestampSigner(salt=CURSOR_SALT)
    access_rev = calculate_access_revision(user, enrollment)
    payload = {
        "user_id": str(user.id) if user and user.is_authenticated else "guest",
        "enrollment_id": str(enrollment.id) if enrollment else None,
        "last_sequence": last_sequence,
        "schema_version": schema_version,
        "access_revision": access_rev,
        "issued_at": int(time.time()),
    }
    return signer.sign_object(payload)


def parse_and_validate_cursor(
    cursor_str: str,
    *,
    user,
    enrollment,
    schema_version: str = "1",
) -> Tuple[Dict[str, Any], bool]:
    """
    Parses and validates a signed cursor string.
    Returns (payload_dict, reset_required: bool).
    Raises ValueError with error code if invalid or expired.
    """
    signer = TimestampSigner(salt=CURSOR_SALT)
    try:
        payload = signer.unsign_object(cursor_str, max_age=CURSOR_MAX_AGE_SECONDS)
    except SignatureExpired:
        raise ValueError("CURSOR_EXPIRED")
    except BadSignature:
        raise ValueError("INVALID_CURSOR")
    except Exception:
        raise ValueError("INVALID_CURSOR")

    if payload.get("schema_version") != schema_version:
        raise ValueError("INVALID_CURSOR_SCHEMA")

    expected_user_id = str(user.id) if user and user.is_authenticated else "guest"
    if payload.get("user_id") != expected_user_id:
        raise ValueError("CURSOR_OWNERSHIP_MISMATCH")

    expected_enrollment_id = str(enrollment.id) if enrollment else None
    if payload.get("enrollment_id") != expected_enrollment_id:
        raise ValueError("CURSOR_ENROLLMENT_MISMATCH")

    current_access_rev = calculate_access_revision(user, enrollment)
    cursor_access_rev = payload.get("access_revision")

    reset_required = (cursor_access_rev != current_access_rev)

    return payload, reset_required
