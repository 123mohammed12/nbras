"""
Registration and Login Service.

Handles guest upgrade, new user registration, student profile creation,
and phone OTP login with verification grant validation.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.accounts.exceptions import (
    AccountInactiveError,
    AccountNotFoundError,
    PhoneAlreadyExistsError,
)
from apps.accounts.models import User, UserDevice, StudentProfile, normalize_phone
from apps.accounts.services.device_service import register_or_update_device
from apps.accounts.services.otp_service import consume_verification_grant
from apps.accounts.services.session_service import create_user_session

logger = logging.getLogger("accounts.services")


@transaction.atomic
def upgrade_guest_to_registered_user(
    guest_user: User,
    phone: str,
    verification: "PhoneVerification",  # noqa: F821 — forward ref
    device_data: dict,
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[User, UserDevice, dict]:
    """
    Upgrade an existing GUEST user account to a REGISTERED user account.
    Maintains the existing User UUID without creating a new user row!

    The verification grant must already be consumed before calling this.
    """
    normalized_phone = normalize_phone(phone)

    # Lock and check if phone is already taken by another registered user
    existing_user = (
        User.objects.select_for_update()
        .filter(phone=normalized_phone)
        .exclude(id=guest_user.id)
        .first()
    )
    if existing_user:
        raise PhoneAlreadyExistsError("رقم الهاتف مرتبط بحساب مسجل بالفعل.")

    # Mutate guest user to registered
    now = timezone.now()
    guest_user.account_type = User.AccountType.REGISTERED
    guest_user.phone = normalized_phone
    guest_user.phone_verified_at = now
    guest_user.upgraded_at = now
    from django.db import IntegrityError

    try:
        with transaction.atomic():
            guest_user.save(
                update_fields=[
                    "account_type",
                    "phone",
                    "phone_verified_at",
                    "upgraded_at",
                    "updated_at",
                ]
            )
    except IntegrityError:
        raise PhoneAlreadyExistsError("رقم الهاتف مرتبط بحساب مسجل بالفعل.")

    # Update device
    device = register_or_update_device(
        user=guest_user,
        installation_id=device_data["installation_id"],
        platform=device_data.get("platform", "android"),
        device_name=device_data.get("device_name", ""),
        operating_system=device_data.get("operating_system", ""),
        app_version=device_data.get("app_version", ""),
    )

    # Create new session
    tokens = create_user_session(
        user=guest_user,
        device=device,
        request_ip=request_ip,
        user_agent=user_agent,
    )

    return guest_user, device, tokens


@transaction.atomic
def register_new_user(
    phone: str,
    verification: "PhoneVerification",  # noqa: F821 — forward ref
    device_data: dict,
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[User, UserDevice, dict]:
    """
    Register a brand new user directly (without an existing guest session).

    The verification grant must already be consumed before calling this.
    """
    normalized_phone = normalize_phone(phone)

    if User.objects.filter(phone=normalized_phone).exists():
        raise PhoneAlreadyExistsError("رقم الهاتف مسجل بالفعل.")

    from django.db import IntegrityError
    
    now = timezone.now()
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                phone=normalized_phone,
                phone_verified_at=now,
                account_type=User.AccountType.REGISTERED,
            )
    except IntegrityError:
        raise PhoneAlreadyExistsError("رقم الهاتف مسجل بالفعل.")

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
def login_registered_user(
    phone: str,
    verification: "PhoneVerification",  # noqa: F821 — forward ref
    device_data: dict,
    request_ip: str | None = None,
    user_agent: str = "",
) -> tuple[User, UserDevice, dict]:
    """
    Log in an existing registered user after verification grant validation.

    The verification grant must already be consumed before calling this.
    """
    normalized_phone = normalize_phone(phone)

    user = User.objects.filter(phone=normalized_phone).first()
    if not user:
        # Generic error to avoid revealing if phone is registered
        raise AccountNotFoundError("تعذر تسجيل الدخول. يرجى التحقق من البيانات.")

    if not user.is_active:
        raise AccountInactiveError()

    # Update last_login
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

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


def create_or_update_student_profile(
    user: User,
    full_name: str,
    governorate_id: int | None = None,
    district_id: int | None = None,
    isolation_id: int | None = None,
    school_id: int | None = None,
    custom_school_name: str = "",
) -> StudentProfile:
    """
    Create or update the student profile for a user.
    """
    profile, _ = StudentProfile.objects.get_or_create(user=user, defaults={"full_name": full_name})
    profile.full_name = full_name
    profile.governorate_id = governorate_id
    profile.district_id = district_id
    profile.isolation_id = isolation_id
    profile.school_id = school_id
    profile.custom_school_name = custom_school_name.strip()
    profile.full_clean()
    profile.save()
    return profile
