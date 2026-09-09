"""
Authentication API Views.

All views use verification grant flow:
1. OTP Request → sends code
2. OTP Verify → returns verification_grant
3. Register/Login → consumes verification_grant

Security (BE-12AR):
- Installation ID resolved via central helper (X-Installation-Id header is primary).
- No default-device-installation-id fallback.
- Token refresh response wrapped in success/data envelope (matches current Flutter contract).
"""

import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, normalize_phone
from apps.accounts.serializers import (
    GuestCreateSerializer,
    LoginPasswordSerializer,
    LoginSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    PasswordChangeSerializer,
    PasswordResetCompleteSerializer,
    RegisterCompleteSerializer,
    RegisterPasswordCompleteSerializer,
    TokenRefreshSerializer,
    TokenPairSerializer,
    UserSerializer,
)
from apps.accounts.services import (
    change_user_password,
    consume_verification_grant,
    create_guest_user,
    create_or_update_student_profile,
    login_registered_user,
    login_user_with_password,
    merge_guest_account,
    register_new_user,
    register_user_with_password,
    request_phone_otp,
    reset_user_password_with_grant,
    revoke_all_sessions,
    rotate_refresh_token,
    upgrade_guest_to_registered_user,
    verify_phone_otp,
)
from apps.accounts.services.installation_id import build_device_data
from apps.accounts.throttles import (
    GuestCreateThrottle,
    LoginThrottle,
    OTPRequestThrottle,
    OTPVerifyThrottle,
    PasswordChangeThrottle,
    PasswordResetCompleteThrottle,
    RegistrationCompleteThrottle,
    TokenRefreshThrottle,
    PasswordLoginPhoneThrottle,
    PasswordLoginIPThrottle,
    PasswordRegistrationPhoneThrottle,
    PasswordRegistrationIPThrottle,
    PasswordResetPhoneThrottle,
    PasswordResetIPThrottle,
)
from apps.common.api import created_response, success_response
from apps.common.idempotency import idempotent_view

logger = logging.getLogger("accounts.views")


class GuestCreateAPIView(APIView):
    """Create or restore a guest user account."""

    permission_classes = [AllowAny]
    throttle_classes = [GuestCreateThrottle]

    @extend_schema(
        request=GuestCreateSerializer,
        responses={201: UserSerializer},
        summary="إنشاء أو استعادة حساب زائر",
        tags=["Auth"],
    )
    @idempotent_view
    def post(self, request, *args, **kwargs):
        serializer = GuestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, device, tokens = create_guest_user(
            installation_id=serializer.validated_data["installation_id"],
            platform=serializer.validated_data.get("platform", "android"),
            device_name=serializer.validated_data.get("device_name", ""),
            operating_system=serializer.validated_data.get("operating_system", ""),
            app_version=serializer.validated_data.get("app_version", ""),
            request_ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        user_data = UserSerializer(user).data
        return created_response(
            data={
                "user": user_data,
                "tokens": tokens,
                "requires_study_selection": True,
            }
        )


class OTPRequestAPIView(APIView):
    """Request an OTP code to be sent via SMS."""

    permission_classes = [AllowAny]
    throttle_classes = [OTPRequestThrottle]

    @extend_schema(
        request=OTPRequestSerializer,
        responses={200: inline_serializer("OTPRequestResponse", fields={
            "request_id": drf_serializers.UUIDField(),
            "phone": drf_serializers.CharField(),
            "expires_at": drf_serializers.DateTimeField(),
        })},
        summary="طلب إرسال رمز التحقق OTP",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification = request_phone_otp(
            phone=serializer.validated_data["phone"],
            purpose=serializer.validated_data["purpose"],
            request_ip=request.META.get("REMOTE_ADDR"),
            installation_id=serializer.validated_data.get("installation_id"),
        )

        return success_response(
            data={
                "request_id": str(verification.request_id),
                "phone": verification.phone,
                "expires_at": verification.expires_at,
            }
        )


class OTPVerifyAPIView(APIView):
    """Verify an OTP code and receive a verification grant."""

    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyThrottle]

    @extend_schema(
        request=OTPVerifySerializer,
        responses={200: inline_serializer("OTPVerifyResponse", fields={
            "verified": drf_serializers.BooleanField(),
            "request_id": drf_serializers.UUIDField(),
            "verification_grant": drf_serializers.CharField(),
            "phone": drf_serializers.CharField(),
        })},
        summary="التحقق من رمز OTP",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification, grant_token = verify_phone_otp(
            request_id=str(serializer.validated_data["request_id"]),
            phone=serializer.validated_data["phone"],
            code=serializer.validated_data["code"],
            purpose=serializer.validated_data["purpose"],
        )

        return success_response(
            data={
                "verified": True,
                "request_id": str(verification.request_id),
                "verification_grant": grant_token,
                "phone": verification.phone,
            }
        )


class RegisterCompleteAPIView(APIView):
    """Complete user registration with verification grant."""

    permission_classes = [AllowAny]
    throttle_classes = [RegistrationCompleteThrottle]

    @extend_schema(
        request=RegisterCompleteSerializer,
        responses={200: UserSerializer},
        summary="إكمال التسجيل أو ترقية الزائر",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = RegisterCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        phone = data["phone"]
        otp_req_id = str(data["otp_request_id"])
        grant = data["verification_grant"]
        dev_data = data["device"]

        with transaction.atomic():
            # 1. Consume verification grant (one-time, atomic)
            verification = consume_verification_grant(
                request_id=otp_req_id,
                verification_grant=grant,
                phone=phone,
                purpose="register",
            )

            # 2. Determine registration path
            current_user = request.user if request.user.is_authenticated else None
            is_guest = current_user and current_user.is_guest

            norm_phone = normalize_phone(phone)
            existing_target = User.objects.filter(
                phone=norm_phone,
                account_type=User.AccountType.REGISTERED,
            ).first()

            if is_guest and existing_target:
                # Case B: Merge guest into target user
                if not existing_target.is_active:
                    from apps.accounts.exceptions import AccountInactiveError
                    raise AccountInactiveError()

                merge_rec, tokens = merge_guest_account(
                    source_guest=current_user,
                    target_user=existing_target,
                    device_data=dev_data,
                    request_ip=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
                user = existing_target
            elif is_guest:
                # Case A: Upgrade guest in-place
                user, device, tokens = upgrade_guest_to_registered_user(
                    guest_user=current_user,
                    phone=phone,
                    verification=verification,
                    device_data=dev_data,
                    request_ip=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
            else:
                # Case C: Direct new user registration
                user, device, tokens = register_new_user(
                    phone=phone,
                    verification=verification,
                    device_data=dev_data,
                    request_ip=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )

            # 3. Create or update Student Profile
            profile = create_or_update_student_profile(
                user=user,
                full_name=data["full_name"],
                governorate_id=data.get("governorate_id"),
                district_id=data.get("district_id"),
                isolation_id=data.get("isolation_id"),
                school_id=data.get("school_id"),
                custom_school_name=data.get("custom_school_name", ""),
            )

            # 4. Create Study Enrollment (cross-app, required)
            from apps.curriculum.services.enrollment_service import create_study_enrollment

            create_study_enrollment(
                user=user,
                grade_id=data["grade_id"],
                section_id=data.get("track_id"),
            )

        return success_response(
            data={
                "user": UserSerializer(user).data,
                "tokens": tokens,
            }
        )


class LoginAPIView(APIView):
    """Log in via phone + verification grant."""

    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        request=LoginSerializer,
        responses={200: UserSerializer},
        summary="تسجيل الدخول برقم الهاتف",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            # Consume verification grant
            verification = consume_verification_grant(
                request_id=str(data["otp_request_id"]),
                verification_grant=data["verification_grant"],
                phone=data["phone"],
                purpose="login",
            )

            user, device, tokens = login_registered_user(
                phone=data["phone"],
                verification=verification,
                device_data=data["device"],
                request_ip=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

        return success_response(
            data={
                "user": UserSerializer(user).data,
                "tokens": tokens,
            }
        )


class TokenRefreshAPIView(APIView):
    """Refresh access token using a refresh token."""

    permission_classes = [AllowAny]
    throttle_classes = [TokenRefreshThrottle]

    @extend_schema(
        request=TokenRefreshSerializer,
        responses={200: TokenPairSerializer},
        summary="تجديد رمز الوصول",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tokens = rotate_refresh_token(
            refresh_token_str=serializer.validated_data["refresh"],
            request_ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        return Response(tokens)


class LogoutAPIView(APIView):
    """Log out and revoke current session."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=inline_serializer("LogoutRequest", fields={
            "refresh": drf_serializers.CharField(required=False),
        }),
        responses={200: inline_serializer("LogoutResponse", fields={
            "message": drf_serializers.CharField(),
        })},
        summary="تسجيل الخروج",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        refresh = request.data.get("refresh")
        sid = request.auth.get("sid") if request.auth is not None else None
        if sid:
            from apps.accounts.services.session_service import revoke_session
            revoke_session(sid, request.user)
        from apps.notifications.models import PushDevice
        # Includes invalid/absent refresh-token requests; scoped to the caller's installation.
        PushDevice.objects.filter(device__user=request.user, installation_id=request.headers.get("X-Installation-Id", "")).update(active=False)
        if refresh:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken

                token = RefreshToken(refresh)
                jti = token.get("jti")
                from apps.accounts.models import UserSession

                from apps.notifications.services import disable_devices
                sessions = UserSession.objects.filter(
                    refresh_token_jti=jti,
                    user=request.user,
                )
                disable_devices(sessions.values("device_id"))
                sessions.update(revoked_at=timezone.now())
            except Exception:
                pass  # Token may already be invalid

        return success_response(data={"message": "تم تسجيل الخروج بنجاح."})


class LogoutAllAPIView(APIView):
    """Log out from all sessions."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: inline_serializer("LogoutAllResponse", fields={
            "message": drf_serializers.CharField(),
        })},
        summary="تسجيل الخروج من جميع الجلسات",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        count = revoke_all_sessions(request.user)
        return success_response(data={"message": f"تم تسجيل الخروج من جميع الجلسات ({count})."})


class RegisterPasswordCompleteAPIView(APIView):
    """Complete user registration with phone + password + verification grant."""

    permission_classes = [AllowAny]
    throttle_classes = [PasswordRegistrationPhoneThrottle, PasswordRegistrationIPThrottle]

    @extend_schema(
        request=RegisterPasswordCompleteSerializer,
        parameters=[
            OpenApiParameter(
                name="X-Installation-Id",
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description="معرف التثبيت للجهاز",
            ),
        ],
        responses={
            200: inline_serializer(
                "RegisterPasswordResponse",
                fields={
                    "success": drf_serializers.BooleanField(default=True),
                    "data": inline_serializer(
                        "RegisterPasswordData",
                        fields={
                            "user": UserSerializer(),
                            "tokens": TokenPairSerializer(),
                        },
                    ),
                },
            ),
        },
        summary="إكمال التسجيل بكلمة المرور",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = RegisterPasswordCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        otp_req_id = str(data["otp_request_id"]) if data.get("otp_request_id") else None

        # Resolve Installation ID via central helper
        device_data = build_device_data(request, body_device_data=data.get("device"), required=True)

        user, device, tokens = register_user_with_password(
            phone=data["phone"],
            password=data["password"],
            password_confirm=data["password_confirm"],
            verification_grant=data["verification_grant"],
            device_data=device_data,
            full_name=data["full_name"],
            otp_request_id=otp_req_id,
            current_user=request.user if request.user.is_authenticated else None,
            governorate_id=data.get("governorate_id"),
            district_id=data.get("district_id"),
            isolation_id=data.get("isolation_id"),
            school_id=data.get("school_id"),
            custom_school_name=data.get("custom_school_name", ""),
            grade_id=data.get("grade_id"),
            track_id=data.get("track_id"),
            request_ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        return success_response(
            data={
                "user": UserSerializer(user).data,
                "tokens": tokens,
            }
        )


class LoginPasswordAPIView(APIView):
    """Log in via phone + password."""

    permission_classes = [AllowAny]
    throttle_classes = [PasswordLoginPhoneThrottle, PasswordLoginIPThrottle]

    @extend_schema(
        request=LoginPasswordSerializer,
        parameters=[
            OpenApiParameter(
                name="X-Installation-Id",
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description="معرف التثبيت للجهاز",
            ),
        ],
        responses={
            200: inline_serializer(
                "LoginPasswordResponse",
                fields={
                    "success": drf_serializers.BooleanField(default=True),
                    "data": inline_serializer(
                        "LoginPasswordData",
                        fields={
                            "user": UserSerializer(),
                            "tokens": TokenPairSerializer(),
                        },
                    ),
                },
            ),
        },
        summary="تسجيل الدخول برقم الهاتف وكلمة المرور",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = LoginPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Resolve Installation ID via central helper — no default fallback
        device_data = build_device_data(request, body_device_data=data.get("device"), required=True)

        user, device, tokens = login_user_with_password(
            phone=data["phone"],
            password=data["password"],
            device_data=device_data,
            source_guest=request.user if request.user.is_authenticated and request.user.is_guest else None,
            request_ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        return success_response(
            data={
                "user": UserSerializer(user).data,
                "tokens": tokens,
            }
        )


class PasswordResetCompleteAPIView(APIView):
    """Complete password reset using verification grant."""

    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetPhoneThrottle, PasswordResetIPThrottle]

    @extend_schema(
        request=PasswordResetCompleteSerializer,
        responses={
            200: inline_serializer(
                "PasswordResetSuccessEnvelope",
                fields={
                    "success": drf_serializers.BooleanField(default=True),
                    "data": inline_serializer(
                        "PasswordResetData",
                        fields={"message": drf_serializers.CharField()},
                    ),
                },
            ),
        },
        summary="إكمال إعادة تعيين كلمة المرور",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        otp_req_id = str(data["otp_request_id"]) if data.get("otp_request_id") else None

        user = reset_user_password_with_grant(
            phone=data["phone"],
            verification_grant=data["verification_grant"],
            new_password=data["new_password"],
            new_password_confirm=data["new_password_confirm"],
            otp_request_id=otp_req_id,
        )

        return success_response(data={"message": "تم إعادة تعيين كلمة المرور بنجاح."})


class PasswordChangeAPIView(APIView):
    """Change password for an authenticated user."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PasswordChangeThrottle]

    @extend_schema(
        request=PasswordChangeSerializer,
        parameters=[
            OpenApiParameter(
                name="X-Installation-Id",
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description="معرف التثبيت للجهاز",
            ),
        ],
        responses={
            200: inline_serializer(
                "PasswordChangeSuccessEnvelope",
                fields={
                    "success": drf_serializers.BooleanField(default=True),
                    "data": inline_serializer(
                        "PasswordChangeData",
                        fields={
                            "message": drf_serializers.CharField(),
                            "tokens": TokenPairSerializer(),
                        },
                    ),
                },
            ),
        },
        summary="تغيير كلمة المرور للمستخدم المسجل",
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Resolve Installation ID for the new session (required=True for session issuance)
        device_data = build_device_data(request, body_device_data=data.get("device"), required=True)

        user, tokens = change_user_password(
            user=request.user,
            current_password=data["current_password"],
            new_password=data["new_password"],
            new_password_confirm=data["new_password_confirm"],
            device_data=device_data,
            request_ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        return success_response(data={
            "message": "تم تغيير كلمة المرور بنجاح.",
            "tokens": tokens,
        })
