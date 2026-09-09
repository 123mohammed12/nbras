"""
Password Authentication Services.

Handles password registration, password login, password reset completion,
and password change with Django password validators and session invalidation.

Security fixes (BE-12AR):
- Registration never overwrites existing user's password.
- Reset accepts only RESET_PASSWORD purpose (no RECOVER_ACCOUNT fallback).
- Reset uses generic INVALID_PASSWORD_RESET_PROOF to prevent account enumeration.
- Login performs dummy hash check to prevent timing enumeration.
- Password validation errors mapped to stable codes.
"""

import logging

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.exceptions import PermissionDenied

from apps.accounts.exceptions import (
    AccountInactiveError,
    InvalidCredentialsError,
    InvalidPasswordError,
    InvalidPasswordResetProofError,
    PhoneAlreadyExistsError,
    VerificationGrantError,
)
from apps.accounts.models import PhoneVerification, User, UserDevice, normalize_phone
from apps.accounts.services.device_service import register_or_update_device
from apps.accounts.services.otp_service import consume_verification_grant
from apps.accounts.services.registration_service import (
    create_or_update_student_profile,
    register_new_user,
    upgrade_guest_to_registered_user,
)
from apps.accounts.services.session_service import create_user_session, revoke_all_sessions

logger = logging.getLogger("accounts.services")

# Pre-computed dummy password hash for timing-safe login checks.
# Used when user doesn't exist / is guest / has unusable password.
_DUMMY_PASSWORD_HASH = make_password("dummy-password-for-timing-equalization")

# Mapping from Django validator class names or error codes to stable project error codes.
_PASSWORD_VALIDATOR_CODE_MAP = {
    "MinimumLengthValidator": "PASSWORD_TOO_SHORT",
    "CommonPasswordValidator": "PASSWORD_TOO_COMMON",
    "NumericPasswordValidator": "PASSWORD_ENTIRELY_NUMERIC",
    "UserAttributeSimilarityValidator": "PASSWORD_TOO_SIMILAR",
    "password_too_short": "PASSWORD_TOO_SHORT",
    "password_too_common": "PASSWORD_TOO_COMMON",
    "password_too_numeric": "PASSWORD_ENTIRELY_NUMERIC",
    "password_entirely_numeric": "PASSWORD_ENTIRELY_NUMERIC",
    "password_too_similar": "PASSWORD_TOO_SIMILAR",
}


def validate_password_strength(
    password: str,
    user: User | None = None,
    field_name: str = "password",
) -> None:
    """
    Validate password using standard Django password validators.

    Raises DRF ValidationError with the specified field_name key.
    Maps Django validator errors to stable project codes.
    """
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        error_messages = []
        for error in exc.error_list:
            raw_code = getattr(error, "code", None)
            if not raw_code and hasattr(error, "params") and error.params and "validator" in error.params:
                validator = error.params["validator"]
                raw_code = type(validator).__name__
            
            code = _PASSWORD_VALIDATOR_CODE_MAP.get(raw_code, raw_code)
            if code and not str(code).isupper():
                code = str(code).upper()
            
            msg = error.messages[0] if getattr(error, "messages", None) else str(error.message)
            error_messages.append(drf_serializers.ErrorDetail(msg, code=code or "VALIDATION_ERROR"))
        raise drf_serializers.ValidationError({field_name: error_messages})


@transaction.atomic
def register_user_with_password(
    phone: str,
    password: str,
    password_confirm: str,
    verification_grant: str,
    device_data: dict,
    full_name: str,
    otp_request_id: str | None = None,
    current_user: User | None = None,
    governorate_id: int | None = None,
    district_id: int | None = None,
    isolation_id: int | None = None,
    school_id: int | None = None,
    custom_school_name: str = "",
    grade_id: str | None = None,
    track_id: str | None = None,
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[User, UserDevice, dict]:
    """
    Complete registration or guest upgrade using phone + password + verification grant.

    Security policy (BE-12AR):
    - If the phone is already registered, return PHONE_ALREADY_EXISTS.
    - Never overwrite an existing user's password from the registration path.
    - Grant is consumed only after all pre-checks pass (rollback on error).
    """
    if password != password_confirm:
        raise drf_serializers.ValidationError(
            {"password_confirm": [drf_serializers.ErrorDetail("كلمتا المرور غير متطابقتين.", code="PASSWORD_MISMATCH")]}
        )

    norm_phone = normalize_phone(phone)
    temp_user = current_user or User(phone=norm_phone)
    validate_password_strength(password, user=temp_user, field_name="password")

    # ── Pre-check: reject if phone already registered ──
    # This runs BEFORE consuming the grant so the grant stays usable.
    norm_phone = normalize_phone(phone)
    existing_target = User.objects.filter(
        phone=norm_phone,
        account_type=User.AccountType.REGISTERED,
    ).first()

    is_guest = current_user and current_user.is_guest

    if existing_target:
        # Whether the caller is anonymous or a guest, we never overwrite
        # an existing registered account's password via the registration path.
        # Direct the client to login or reset instead.
        raise PhoneAlreadyExistsError()

    # ── Consume verification grant (one-time, atomic via outer transaction) ──
    verification = consume_verification_grant(
        request_id=otp_request_id,
        verification_grant=verification_grant,
        phone=phone,
        purpose="register",
    )

    # ── Determine registration path ──
    if is_guest:
        user, device, tokens = upgrade_guest_to_registered_user(
            guest_user=current_user,
            phone=phone,
            verification=verification,
            device_data=device_data,
            request_ip=request_ip,
            user_agent=user_agent,
        )
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
    else:
        user, device, tokens = register_new_user(
            phone=phone,
            verification=verification,
            device_data=device_data,
            request_ip=request_ip,
            user_agent=user_agent,
        )
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])

    # ── Create or update Student Profile ──
    create_or_update_student_profile(
        user=user,
        full_name=full_name,
        governorate_id=governorate_id,
        district_id=district_id,
        isolation_id=isolation_id,
        school_id=school_id,
        custom_school_name=custom_school_name,
    )

    # ── Create Study Enrollment if grade_id provided ──
    if grade_id:
        from apps.curriculum.services.enrollment_service import create_study_enrollment

        create_study_enrollment(
            user=user,
            grade_id=grade_id,
            section_id=track_id,
        )

    return user, device, tokens


@transaction.atomic
def login_user_with_password(
    phone: str,
    password: str,
    device_data: dict,
    source_guest: User | None = None,
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[User, UserDevice, dict]:
    """
    Authenticate user via phone and password securely.

    Timing-safe: performs a dummy hash check when user doesn't exist,
    is a guest, or has no usable password to prevent timing enumeration.
    """
    norm_phone = normalize_phone(phone)
    user = User.objects.filter(phone=norm_phone).first()

    # Timing-safe authentication check
    if not user or user.is_guest or not user.has_usable_password():
        # Perform dummy hash check to equalize timing
        check_password(password, _DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError("بيانات الدخول غير صحيحة.")

    if not user.check_password(password):
        raise InvalidCredentialsError("بيانات الدخول غير صحيحة.")

    if not user.is_active:
        raise AccountInactiveError()

    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

    if source_guest and source_guest.is_guest and source_guest.id != user.id:
        from apps.accounts.services.merge_service import merge_guest_account

        _, tokens = merge_guest_account(
            source_guest=source_guest,
            target_user=user,
            device_data=device_data,
            request_ip=request_ip,
            user_agent=user_agent,
        )
        device = UserDevice.objects.filter(
            user=user, installation_id=device_data["installation_id"]
        ).first()
        return user, device, tokens

    device = register_or_update_device(
        user=user,
        installation_id=device_data["installation_id"],
        platform=device_data.get("platform", "android"),
        device_name=device_data.get("device_name", ""),
        operating_system=device_data.get("operating_system", ""),
        app_version=device_data.get("app_version", ""),
    )

    tokens = create_user_session(
        user=user,
        device=device,
        request_ip=request_ip,
        user_agent=user_agent,
    )

    return user, device, tokens


@transaction.atomic
def reset_user_password_with_grant(
    phone: str,
    verification_grant: str,
    new_password: str,
    new_password_confirm: str,
    otp_request_id: str | None = None,
) -> User:
    """
    Reset user password after valid OTP verification grant consumption.
    Revokes all active sessions. Does NOT issue new tokens.

    Security policy (BE-12AR):
    - Accepts ONLY PhoneVerification.Purpose.RESET_PASSWORD (no RECOVER_ACCOUNT fallback).
    - Returns generic INVALID_PASSWORD_RESET_PROOF to prevent account enumeration.
    - Password is only changed after grant is validated for the correct phone and purpose.
    """
    if new_password != new_password_confirm:
        raise drf_serializers.ValidationError(
            {"new_password_confirm": [drf_serializers.ErrorDetail("كلمتا المرور غير متطابقتين.", code="PASSWORD_MISMATCH")]}
        )

    norm_phone = normalize_phone(phone)

    # Consume grant with strict purpose — only RESET_PASSWORD
    try:
        consume_verification_grant(
            request_id=otp_request_id,
            verification_grant=verification_grant,
            phone=phone,
            purpose=PhoneVerification.Purpose.RESET_PASSWORD,
        )
    except VerificationGrantError:
        # Generic error — do not reveal whether the account exists or the grant purpose is wrong
        raise InvalidPasswordResetProofError()

    # Only after grant is verified do we look up the user
    user = User.objects.select_for_update().filter(phone=norm_phone).first()
    if not user:
        # Generic error — do not reveal that the account doesn't exist
        raise InvalidPasswordResetProofError()

    validate_password_strength(new_password, user=user, field_name="new_password")

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])

    from apps.notifications.services import system_event
    import uuid
    system_event(user=user, key=f"password_changed:{uuid.uuid4()}", title="أمان الحساب", body="تم تغيير كلمة المرور لحسابك.", category="ACCOUNT", action_type="OPEN_SETTINGS")

    # Revoke all active sessions for security
    revoke_all_sessions(user)

    return user


@transaction.atomic
def change_user_password(
    user: User,
    current_password: str,
    new_password: str,
    new_password_confirm: str,
    device_data: dict,
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[User, dict]:
    """
    Change user password for an authenticated user.
    Revokes all existing sessions and produces a fresh token pair.
    """
    if user.is_guest:
        raise PermissionDenied("لا يمكن للزائر تغيير كلمة المرور.")

    if not user.check_password(current_password):
        raise InvalidPasswordError("كلمة المرور الحالية غير صحيحة.")

    if new_password != new_password_confirm:
        raise drf_serializers.ValidationError(
            {"new_password_confirm": [drf_serializers.ErrorDetail("كلمتا المرور غير متطابقتين.", code="PASSWORD_MISMATCH")]}
        )

    if current_password == new_password:
        raise drf_serializers.ValidationError(
            {"new_password": ["كلمة المرور الجديدة يجب أن تكون مختلفة عن كلمة المرور الحالية."]}
        )

    validate_password_strength(new_password, user=user, field_name="new_password")

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])

    # Revoke all previous sessions
    from apps.notifications.services import system_event
    import uuid
    system_event(user=user, key=f"password_changed:{uuid.uuid4()}", title="أمان الحساب", body="تم تغيير كلمة المرور لحسابك.", category="ACCOUNT", action_type="OPEN_SETTINGS")
    revoke_all_sessions(user)

    # Issue new session for current user (device_data is required, never device=None)
    device = register_or_update_device(
        user=user,
        installation_id=device_data["installation_id"],
        platform=device_data.get("platform", "android"),
        device_name=device_data.get("device_name", ""),
        operating_system=device_data.get("operating_system", ""),
        app_version=device_data.get("app_version", ""),
    )

    tokens = create_user_session(
        user=user,
        device=device,
        request_ip=request_ip,
        user_agent=user_agent,
    )

    return user, tokens
