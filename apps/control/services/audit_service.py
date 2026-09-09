"""
Central Operational Audit Service (ADM-09).
Provides safe, deterministic, and privacy-aware logging for high-impact actions in /control/.
"""

import logging
from typing import Any
from django.utils import timezone
from apps.control.models import ControlAuditLog

logger = logging.getLogger("control.audit")

FORBIDDEN_METADATA_KEYS = {
    "password", "password_hash", "otp", "otp_hash", "token", "refresh_token",
    "refresh_token_hash", "secret", "fcm_token", "push_token", "api_key",
    "private_key", "secret_key", "activation_code", "raw_code", "credentials",
}


def sanitize_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """
    Ensure metadata is clean, safe, and stripped of sensitive authentication secrets.
    """
    if not meta or not isinstance(meta, dict):
        return {}

    sanitized = {}
    for key, value in meta.items():
        key_str = str(key).lower()
        if any(f_key in key_str for f_key in FORBIDDEN_METADATA_KEYS):
            continue
        if isinstance(value, dict):
            sanitized[key] = sanitize_metadata(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[key] = value
        elif isinstance(value, (list, tuple)):
            sanitized[key] = [
                sanitize_metadata(item) if isinstance(item, dict) else str(item)
                for item in value
            ]
        else:
            sanitized[key] = str(value)

    return sanitized


def record_control_action(
    *,
    action: str,
    target_type: str,
    target_id: str = "",
    target_repr: str = "",
    actor=None,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
    request=None,
) -> ControlAuditLog | None:
    """
    Record a high-impact operational action in the Central Operational Audit Log.
    Safe and non-destructive: failures to log will not fail the primary transaction.
    """
    try:
        # Determine actor
        effective_actor = actor
        ip_addr = None
        req_id = None

        if request is not None:
            if effective_actor is None and hasattr(request, "user") and request.user.is_authenticated:
                effective_actor = request.user
            ip_addr = request.META.get("REMOTE_ADDR")
            req_id = request.META.get("HTTP_X_REQUEST_ID") or request.META.get("HTTP_X_CORRELATION_ID")

        clean_meta = sanitize_metadata(metadata)

        audit_entry = ControlAuditLog.objects.create(
            actor=effective_actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else "",
            target_repr=str(target_repr)[:255] if target_repr else "",
            reason=str(reason) if reason else "",
            metadata=clean_meta,
            request_id=str(req_id)[:100] if req_id else None,
            ip_address=ip_addr,
        )
        return audit_entry
    except Exception as exc:
        logger.warning(
            "Failed to record central control audit log for action=%s target=%s: %s",
            action,
            target_type,
            exc,
        )
        return None
