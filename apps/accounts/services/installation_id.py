"""
Installation ID Resolution Service.

Central helper for resolving the authoritative installation_id from
X-Installation-Id header and/or device body data.

Contract (BE-12AR):
- Primary source: X-Installation-Id header.
- device.installation_id in body is optional if header is present.
- If both are sent, they must match.
- Mismatch → INSTALLATION_ID_MISMATCH.
- Both missing (for session-issuing endpoints) → INSTALLATION_ID_REQUIRED.
"""

from apps.accounts.exceptions import (
    InstallationIdMismatchError,
    InstallationIdRequiredError,
)
from rest_framework.exceptions import ValidationError



def resolve_installation_id(
    request,
    body_device_data: dict | None = None,
    required: bool = True,
) -> str | None:
    """
    Resolve the authoritative installation_id.

    Args:
        request: DRF request object.
        body_device_data: Validated device data from request body (may be None).
        required: If True, raises InstallationIdRequiredError when both sources
                  are missing. Set False for endpoints that don't issue sessions.

    Returns:
        The resolved installation_id string, or None if not required and missing.

    Raises:
        InstallationIdMismatchError: If header and body values differ.
        InstallationIdRequiredError: If required=True and no value found.
    """
    header_id = request.headers.get("X-Installation-Id", "").strip() or None
    body_id = None

    if body_device_data and isinstance(body_device_data, dict):
        body_id = body_device_data.get("installation_id", "").strip() or None

    if required and not header_id:
        raise InstallationIdRequiredError()

    if header_id and body_id and header_id != body_id:
        raise InstallationIdMismatchError()

    resolved = header_id or body_id

    if resolved:
        if len(resolved) < 8 or len(resolved) > 255:
            raise ValidationError({"installation_id": ["يجب أن يكون طول معرف التثبيت بين 8 و 255 حرفًا."]})

    return resolved


def build_device_data(
    request,
    body_device_data: dict | None = None,
    required: bool = True,
) -> dict:
    """
    Build a complete device_data dict with the resolved installation_id.

    Returns a dict suitable for passing to register_or_update_device() and
    other service functions.

    Raises:
        InstallationIdMismatchError: If header and body values differ.
        InstallationIdRequiredError: If required=True and no value found.
    """
    installation_id = resolve_installation_id(
        request,
        body_device_data=body_device_data,
        required=required,
    )

    if body_device_data and isinstance(body_device_data, dict):
        result = dict(body_device_data)
        result["installation_id"] = installation_id
        return result

    return {
        "installation_id": installation_id,
        "platform": "android",
        "device_name": "",
        "operating_system": "",
        "app_version": "",
    }
