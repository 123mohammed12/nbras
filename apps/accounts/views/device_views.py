from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.models import UserDevice
from apps.accounts.serializers import UserDeviceSerializer
from apps.accounts.services.session_service import revoke_device_sessions
from apps.common.api import error_response, success_response


class MeDevicesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserDeviceSerializer(many=True)},
        summary="قائمة أجهزة المستخدم",
        tags=["User Me"],
    )
    def get(self, request, *args, **kwargs):
        devices = UserDevice.objects.filter(user=request.user, is_active=True)
        serializer = UserDeviceSerializer(devices, many=True)
        return success_response(data=serializer.data)


class MeDeviceDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: inline_serializer("DeviceDeleteResponse", fields={"message": drf_serializers.CharField()})},
        summary="إلغاء تفعيل جهاز وتدبير جلساته",
        tags=["User Me"],
    )
    def delete(self, request, device_id, *args, **kwargs):
        device = UserDevice.objects.filter(id=device_id, user=request.user).first()
        if not device:
            return error_response(code="NOT_FOUND", message="الجهاز غير موجود.", status=404)

        device.is_active = False
        device.save(update_fields=["is_active"])

        # Revoke all active sessions on this device
        count = revoke_device_sessions(device)

        return success_response(data={"message": f"تم إيقاف الجهاز وإلغاء {count} جلسة."})
