"""
Device Service.

Registers or updates user devices.
"""

from django.utils import timezone
from apps.accounts.models import User, UserDevice


def register_or_update_device(
    user: User,
    installation_id: str,
    platform: str = "android",
    device_name: str = "",
    operating_system: str = "",
    app_version: str = "",
    push_token: str | None = None,
) -> UserDevice:
    """
    Ensure a device is registered for the user and updated with current metadata.
    """
    device, created = UserDevice.objects.get_or_create(
        user=user,
        installation_id=installation_id,
        defaults={
            "platform": platform,
            "device_name": device_name,
            "operating_system": operating_system,
            "app_version": app_version,
            "push_token": push_token,
            "is_active": True,
        },
    )

    if not created:
        device.platform = platform or device.platform
        if device_name:
            device.device_name = device_name
        if operating_system:
            device.operating_system = operating_system
        if app_version:
            device.app_version = app_version
        if push_token is not None:
            device.push_token = push_token
        device.is_active = True
        device.save()

    return device
