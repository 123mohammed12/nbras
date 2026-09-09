from .guest_service import create_guest_user
from .device_service import register_or_update_device
from .session_service import (
    create_user_session,
    rotate_refresh_token,
    revoke_session,
    revoke_all_sessions,
    revoke_device_sessions,
)
from .otp_service import request_phone_otp, verify_phone_otp, consume_verification_grant
from .registration_service import (
    upgrade_guest_to_registered_user,
    register_new_user,
    login_registered_user,
    create_or_update_student_profile,
)
from .merge_service import merge_guest_account, register_merge_handler
from .password_auth_service import (
    register_user_with_password,
    login_user_with_password,
    reset_user_password_with_grant,
    change_user_password,
    validate_password_strength,
)
from .installation_id import resolve_installation_id, build_device_data

__all__ = [
    "create_guest_user",
    "register_or_update_device",
    "create_user_session",
    "rotate_refresh_token",
    "revoke_session",
    "revoke_all_sessions",
    "revoke_device_sessions",
    "request_phone_otp",
    "verify_phone_otp",
    "consume_verification_grant",
    "upgrade_guest_to_registered_user",
    "register_new_user",
    "login_registered_user",
    "create_or_update_student_profile",
    "merge_guest_account",
    "register_merge_handler",
    "register_user_with_password",
    "login_user_with_password",
    "reset_user_password_with_grant",
    "change_user_password",
    "validate_password_strength",
    "resolve_installation_id",
    "build_device_data",
]
