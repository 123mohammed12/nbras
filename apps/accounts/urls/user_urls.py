"""
User ME URLs under /api/v1/me/
"""

from django.urls import path
from apps.accounts.views import (
    MeUserAPIView,
    MeProfileAPIView,
    MeAccountDeactivationAPIView,
    MeDevicesAPIView,
    MeDeviceDetailAPIView,
    MeSessionsAPIView,
    MeSessionDetailAPIView,
    MeOtherSessionsAPIView,
)

urlpatterns = [
    path("", MeUserAPIView.as_view(), name="me-user"),
    path("profile/", MeProfileAPIView.as_view(), name="me-profile"),
    path("account/deactivate/", MeAccountDeactivationAPIView.as_view(), name="me-account-deactivate"),
    path("devices/", MeDevicesAPIView.as_view(), name="me-devices"),
    path("devices/<uuid:device_id>/", MeDeviceDetailAPIView.as_view(), name="me-device-detail"),
    path("sessions/", MeSessionsAPIView.as_view(), name="me-sessions"),
    path("sessions/others/", MeOtherSessionsAPIView.as_view(), name="me-other-sessions"),
    path("sessions/<uuid:session_id>/", MeSessionDetailAPIView.as_view(), name="me-session-detail"),
]
