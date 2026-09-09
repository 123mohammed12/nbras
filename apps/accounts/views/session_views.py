from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import status
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.models import UserSession
from apps.accounts.serializers import UserSessionSerializer
from apps.accounts.services.installation_id import resolve_installation_id
from apps.accounts.services.session_service import revoke_session
from apps.common.api import error_response, success_response


class MeSessionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserSessionSerializer(many=True)},
        summary="قائمة جلسات المستخدم النشطة",
        tags=["User Me"],
    )
    def get(self, request, *args, **kwargs):
        installation_id = resolve_installation_id(request, required=False)
        sessions = UserSession.objects.filter(
            user=request.user, revoked_at__isnull=True, expires_at__gt=timezone.now()
        ).select_related("device")
        serializer = UserSessionSerializer(sessions, many=True, context={"installation_id": installation_id})
        return success_response(data=serializer.data)


class MeSessionDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: inline_serializer("SessionDeleteResponse", fields={"message": drf_serializers.CharField()})},
        summary="إلغاء جلسة تصفح محددة",
        tags=["User Me"],
    )
    def delete(self, request, session_id, *args, **kwargs):
        if not UserSession.objects.filter(id=session_id, user=request.user).exists():
            return error_response(code="NOT_FOUND", message="الجلسة غير موجودة أو ملغاة بالفعل.", status=404)
        revoked = revoke_session(session_id=session_id, user=request.user)
        return success_response(data={
            "message": "تم إلغاء الجلسة بنجاح." if revoked else "الجلسة ملغاة بالفعل.",
            "revoked": revoked,
        })


class MeOtherSessionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        installation_id = resolve_installation_id(request, required=True)
        if not request.user.devices.filter(installation_id=installation_id, is_active=True).exists():
            return error_response(code="CURRENT_DEVICE_NOT_FOUND", message="تعذر التحقق من الجهاز الحالي.", status=status.HTTP_409_CONFLICT)
        count = UserSession.objects.filter(user=request.user, revoked_at__isnull=True).exclude(
            device__installation_id=installation_id
        ).update(revoked_at=timezone.now())
        return success_response(data={"revoked_count": count})
