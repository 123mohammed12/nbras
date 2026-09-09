"""
Guest Service.

Handles creation of guest user accounts.
"""

import logging
from django.db import transaction
from apps.accounts.models import User, UserDevice
from apps.accounts.services.session_service import create_user_session
from apps.accounts.services.device_service import register_or_update_device

logger = logging.getLogger("accounts.services")


@transaction.atomic
def create_guest_user(
    installation_id: str,
    platform: str = "android",
    device_name: str = "",
    operating_system: str = "",
    app_version: str = "",
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[User, UserDevice, dict]:
    """
    Create a guest user or return existing active session if guest exists for this installation_id.

    Returns:
        (user, device, tokens_dict)
    """

    # Check if an existing guest device exists
    existing_device = UserDevice.objects.filter(
        installation_id=installation_id,
        user__account_type=User.AccountType.GUEST,
        user__is_active=True,
    ).select_related("user").first()

    if existing_device:
        user = existing_device.user
        device = register_or_update_device(
            user=user,
            installation_id=installation_id,
            platform=platform,
            device_name=device_name,
            operating_system=operating_system,
            app_version=app_version,
        )
    else:
        user = User.objects.create_guest()
        device = register_or_update_device(
            user=user,
            installation_id=installation_id,
            platform=platform,
            device_name=device_name,
            operating_system=operating_system,
            app_version=app_version,
        )

    tokens = create_user_session(
        user=user,
        device=device,
        request_ip=request_ip,
        user_agent=user_agent,
    )

    return user, device, tokens
