"""
Authentication URLs under /api/v1/auth/
"""

from django.urls import path
from apps.accounts.views import (
    GuestCreateAPIView,
    LoginAPIView,
    LoginPasswordAPIView,
    LogoutAllAPIView,
    LogoutAPIView,
    OTPRequestAPIView,
    OTPVerifyAPIView,
    PasswordChangeAPIView,
    PasswordResetCompleteAPIView,
    RegisterCompleteAPIView,
    RegisterPasswordCompleteAPIView,
    TokenRefreshAPIView,
)

urlpatterns = [
    path("guest/", GuestCreateAPIView.as_view(), name="auth-guest"),
    path("otp/request/", OTPRequestAPIView.as_view(), name="auth-otp-request"),
    path("otp/verify/", OTPVerifyAPIView.as_view(), name="auth-otp-verify"),
    path("register/complete/", RegisterCompleteAPIView.as_view(), name="auth-register-complete"),
    path("register/password/complete/", RegisterPasswordCompleteAPIView.as_view(), name="auth-register-password-complete"),
    path("login/", LoginAPIView.as_view(), name="auth-login"),
    path("login/password/", LoginPasswordAPIView.as_view(), name="auth-login-password"),
    path("password/reset/complete/", PasswordResetCompleteAPIView.as_view(), name="auth-password-reset-complete"),
    path("password/change/", PasswordChangeAPIView.as_view(), name="auth-password-change"),
    path("token/refresh/", TokenRefreshAPIView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("logout-all/", LogoutAllAPIView.as_view(), name="auth-logout-all"),
]
