"""
Auth Serializers.

Serializers for guest creation, OTP, registration, login, and token refresh.

Security (BE-12AR):
- All password fields: write_only=True, allow_blank=False, trim_whitespace=False, max_length=128.
- trim_whitespace=False prevents silent whitespace stripping that would change the password.
"""

from rest_framework import serializers

from apps.accounts.models import PhoneVerification


class DevicePayloadSerializer(serializers.Serializer):
    installation_id = serializers.CharField(required=True, max_length=255, min_length=8)
    platform = serializers.ChoiceField(choices=["android", "ios", "web"], default="android")
    device_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    operating_system = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    app_version = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)


class OptionalDevicePayloadSerializer(serializers.Serializer):
    installation_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    platform = serializers.ChoiceField(choices=["android", "ios", "web"], required=False)
    device_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    operating_system = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    app_version = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)

class GuestCreateSerializer(serializers.Serializer):
    installation_id = serializers.CharField(required=True, max_length=255, min_length=8)
    platform = serializers.ChoiceField(choices=["android", "ios", "web"], default="android")
    device_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    operating_system = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    app_version = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)


class OTPRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, max_length=20)
    purpose = serializers.ChoiceField(choices=PhoneVerification.Purpose.choices, default="register")
    installation_id = serializers.CharField(required=False, allow_blank=True, max_length=255)


class OTPVerifySerializer(serializers.Serializer):
    request_id = serializers.UUIDField(required=True)
    phone = serializers.CharField(required=True, max_length=20)
    code = serializers.CharField(required=True, min_length=4, max_length=8)
    purpose = serializers.ChoiceField(choices=PhoneVerification.Purpose.choices, default="register")


class RegisterCompleteSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, max_length=20)
    otp_request_id = serializers.UUIDField(required=True)
    verification_grant = serializers.CharField(required=True, max_length=128)
    device = DevicePayloadSerializer(required=True)
    full_name = serializers.CharField(required=True, max_length=255)
    governorate_id = serializers.IntegerField(required=False, allow_null=True)
    district_id = serializers.IntegerField(required=False, allow_null=True)
    isolation_id = serializers.IntegerField(required=False, allow_null=True)
    school_id = serializers.IntegerField(required=False, allow_null=True)
    custom_school_name = serializers.CharField(required=False, allow_blank=True, default="")
    grade_id = serializers.CharField(required=True)
    track_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, max_length=20)
    otp_request_id = serializers.UUIDField(required=True)
    verification_grant = serializers.CharField(required=True, max_length=128)
    device = DevicePayloadSerializer(required=True)


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=True)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="رمز الوصول Access Token (JWT)")
    refresh = serializers.CharField(help_text="رمز التحديث Refresh Token (JWT)")


class RegisterPasswordCompleteSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, max_length=20)
    otp_request_id = serializers.UUIDField(required=False, allow_null=True)
    verification_grant = serializers.CharField(required=True, max_length=128)
    device = OptionalDevicePayloadSerializer(required=False, allow_null=True)
    full_name = serializers.CharField(required=True, max_length=255)
    password = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )
    password_confirm = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )
    governorate_id = serializers.IntegerField(required=False, allow_null=True)
    district_id = serializers.IntegerField(required=False, allow_null=True)
    isolation_id = serializers.IntegerField(required=False, allow_null=True)
    school_id = serializers.IntegerField(required=False, allow_null=True)
    custom_school_name = serializers.CharField(required=False, allow_blank=True, default="")
    grade_id = serializers.CharField(required=True)
    track_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class LoginPasswordSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, max_length=20)
    password = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )
    device = OptionalDevicePayloadSerializer(required=False, allow_null=True)


class PasswordResetCompleteSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, max_length=20)
    verification_grant = serializers.CharField(required=True, max_length=128)
    otp_request_id = serializers.UUIDField(required=False, allow_null=True)
    new_password = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )
    new_password_confirm = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )
    new_password = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )
    new_password_confirm = serializers.CharField(
        required=True, write_only=True, allow_blank=False,
        trim_whitespace=False, max_length=128,
    )
    device = OptionalDevicePayloadSerializer(required=False, allow_null=True)
