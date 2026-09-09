from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.models import StudentProfile, User
from apps.accounts.serializers import AccountDeactivationSerializer, StudentProfileSerializer, UserSerializer
from apps.accounts.services.session_service import revoke_all_sessions
from apps.common.api import error_response, success_response


class MeUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserSerializer},
        summary="بيانات حساب المستخدم الحالي",
        tags=["User Me"],
    )
    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        return success_response(data=serializer.data)


class MeProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _profile(self, user):
        return StudentProfile.objects.select_related(
            "user", "governorate", "district", "isolation", "school"
        ).filter(user=user).first()

    def get(self, request, *args, **kwargs):
        profile = self._profile(request.user)
        if not profile:
            return error_response(code="PROFILE_NOT_FOUND", message="الملف الشخصي غير موجود.", status=status.HTTP_404_NOT_FOUND)
        return success_response(data=StudentProfileSerializer(profile).data)

    def patch(self, request, *args, **kwargs):
        if not request.user.is_registered:
            return error_response(code="REGISTERED_ACCOUNT_REQUIRED", message="هذه العملية متاحة للحساب المسجل فقط.", status=status.HTTP_403_FORBIDDEN)
        profile = self._profile(request.user)
        if not profile:
            return error_response(code="PROFILE_NOT_FOUND", message="الملف الشخصي غير موجود.", status=status.HTTP_404_NOT_FOUND)
        serializer = StudentProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=StudentProfileSerializer(self._profile(request.user)).data)


class MeAccountDeactivationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        if not request.user.is_registered:
            return error_response(code="REGISTERED_ACCOUNT_REQUIRED", message="هذه العملية متاحة للحساب المسجل فقط.", status=status.HTTP_403_FORBIDDEN)
        serializer = AccountDeactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not user.check_password(serializer.validated_data["current_password"]):
            return error_response(
                code="INVALID_CURRENT_PASSWORD", message="كلمة المرور الحالية غير صحيحة.",
                fields={"current_password": ["كلمة المرور الحالية غير صحيحة."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        revoke_all_sessions(user)
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
        return success_response(data={
            "deactivated": True,
            "policy": "تم تعطيل الحساب مع الاحتفاظ بالسجلات التعليمية غير المعدلة لحماية سلامة النتائج والاشتراكات.",
        })
