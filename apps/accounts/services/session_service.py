"""
Session Service.

Manages JWT token creation, rotation, and session revocation.
"""

import hashlib
import uuid
import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from apps.accounts.exceptions import InvalidRefreshTokenError, SessionRevokedError
from apps.accounts.models import User, UserDevice, UserSession

logger = logging.getLogger("accounts.services")


def hash_token(token_str: str) -> str:
    """Hash token string using SHA-256."""
    return hashlib.sha256(token_str.encode("utf-8")).hexdigest()


def create_user_session(
    user: User,
    device: UserDevice | None = None,
    request_ip: str | None = None,
    user_agent: str = "",
) -> dict:
    """
    Generate SimpleJWT Refresh & Access Tokens, record UserSession in DB.

    Returns:
        {"access": "...", "refresh": "..."}
    """
    refresh = RefreshToken.for_user(user)
    if device:
        from apps.notifications.models import PushDevice
        PushDevice.objects.filter(installation_id=device.installation_id).exclude(device=device).update(active=False)
    session_id = uuid.uuid4()
    refresh["sid"] = str(session_id)
    jti = refresh.get("jti")
    exp_timestamp = refresh.get("exp")
    expires_at = datetime.fromtimestamp(exp_timestamp, tz=dt_timezone.utc)

    refresh_str = str(refresh)
    access_str = str(refresh.access_token)

    UserSession.objects.create(
        id=session_id,
        user=user,
        device=device,
        refresh_token_jti=jti,
        refresh_token_hash=hash_token(refresh_str),
        expires_at=expires_at,
        last_ip=request_ip,
        user_agent=user_agent,
    )

    return {
        "access": access_str,
        "refresh": refresh_str,
    }


@transaction.atomic
def rotate_refresh_token(
    refresh_token_str: str,
    request_ip: str | None = None,
    user_agent: str = "",
) -> dict:
    """
    Rotate a refresh token:
    1. Parse and validate JWT token.
    2. Lock and check if session exists in DB and is NOT revoked.
    3. Verify user is still active.
    4. Revoke current session.
    5. Issue new refresh & access token session.
    """
    try:
        token = RefreshToken(refresh_token_str)
    except TokenError as e:
        raise InvalidRefreshTokenError(f"رمز التحديث غير صالح: {str(e)}")

    jti = token.get("jti")

    # Lock session row to prevent concurrent rotation
    session = (
        UserSession.objects.select_for_update(of=("self",))
        .filter(refresh_token_jti=jti)
        .select_related("user", "device")
        .first()
    )

    if not session:
        raise InvalidRefreshTokenError("الجلسة غير موجودة.")

    if session.is_revoked:
        # Security incident: reuse of revoked token! Revoke all sessions for user.
        logger.warning(
            "Token reuse detected for user %s (jti=%s). Revoking all sessions.",
            session.user_id,
            jti,
        )
        revoke_all_sessions(session.user)
        raise SessionRevokedError("تم إلغاء الجلسة لاحتمال استخدام رمز غير آمن.")

    if session.expires_at <= timezone.now():
        raise InvalidRefreshTokenError("انتهت صلاحية الجلسة.")

    # Verify user is still active
    if not session.user.is_active:
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at"])
        raise InvalidRefreshTokenError("الحساب غير نشط.")

    # Mark old session as revoked
    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at"])

    # Create new session
    return create_user_session(
        user=session.user,
        device=session.device,
        request_ip=request_ip or session.last_ip,
        user_agent=user_agent or session.user_agent,
    )


@transaction.atomic
def revoke_session(session_id: str, user: User) -> bool:
    """
    Revoke a specific session owned by the user.
    """
    from apps.notifications.services import disable_devices
    User.objects.select_for_update().get(pk=user.pk)
    disable_devices(UserSession.objects.filter(id=session_id, user=user).values("device_id"))
    updated = UserSession.objects.filter(
        id=session_id,
        user=user,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    return updated > 0


@transaction.atomic
def revoke_all_sessions(user: User, except_session_id: str | None = None) -> int:
    """
    Revoke all active sessions for a user (useful for logout-all or security resets).
    """
    User.objects.select_for_update().get(pk=user.pk)
    qs = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if except_session_id:
        qs = qs.exclude(id=except_session_id)
    from apps.notifications.services import disable_devices
    # A guest merge may already have transferred the device to the target user.
    disable_devices(qs.filter(device__user=user).values("device_id"))
    return qs.update(revoked_at=timezone.now())


def revoke_device_sessions(device: UserDevice) -> int:
    """
    Revoke all sessions associated with a specific device.
    """
    from apps.notifications.services import disable_devices
    disable_devices([device.pk])
    return UserSession.objects.filter(
        device=device,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
