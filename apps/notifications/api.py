from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from apps.accounts.models import UserSession
from apps.common.api import success_response
from apps.common.pagination import StandardPagination
from .models import NotificationPreference, NotificationRecipient, PushDevice
from .services import register_device


def inbox(user):
    return NotificationRecipient.objects.filter(user=user, notification__status__in=["PUBLISHED", "EXPIRED"], notification__published_at__isnull=False).select_related("notification")


def recipient_data(r):
    n = r.notification
    expired = bool(n.expires_at and n.expires_at <= timezone.now())
    return {"id": str(r.pk), "notification_id": str(n.pk), "title": n.title, "body": n.body, "category": n.category, "category_label": n.get_category_display(), "priority": n.priority, "action_type": "NONE" if expired else n.action_type, "action_payload": {} if expired else n.action_payload, "read_at": r.read_at, "created_at": r.created_at, "expired": expired}


class InboxView(APIView):
    def get(self, request):
        qs = inbox(request.user)
        if request.query_params.get("unread") == "true":
            qs = qs.filter(read_at__isnull=True)
        if request.query_params.get("category"):
            qs = qs.filter(notification__category=request.query_params["category"])
        paginator = StandardPagination()
        return paginator.get_paginated_response([recipient_data(r) for r in paginator.paginate_queryset(qs, request)])


class DetailView(APIView):
    def get(self, request, pk):
        return success_response(recipient_data(get_object_or_404(inbox(request.user), pk=pk)))


class UnreadCountView(APIView):
    def get(self, request):
        return success_response({"unread_count": inbox(request.user).filter(read_at__isnull=True).count()})


class ReadView(APIView):
    def post(self, request, pk):
        r = get_object_or_404(inbox(request.user), pk=pk)
        if r.read_at is None:
            NotificationRecipient.objects.filter(pk=r.pk, read_at__isnull=True).update(read_at=timezone.now())
        r.refresh_from_db()
        return success_response(recipient_data(r))


class ReadAllView(APIView):
    def post(self, request):
        count = inbox(request.user).filter(read_at__isnull=True).update(read_at=timezone.now())
        return success_response({"updated": count, "unread_count": inbox(request.user).filter(read_at__isnull=True).count()})


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["learning_content", "assessment", "subscription", "announcements"]


class PreferencesView(APIView):
    def get(self, request):
        p, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return success_response(PreferenceSerializer(p).data)

    def patch(self, request):
        p, _ = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = PreferenceSerializer(p, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(serializer.data)


class DeviceSerializer(serializers.Serializer):
    installation_id = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(choices=["android"])
    fcm_token = serializers.CharField(max_length=1024, trim_whitespace=True, write_only=True)


class DeviceView(APIView):
    def post(self, request):
        serializer = DeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        # New access tokens include sid, checked against the revocable DB session.
        sid = request.auth.get("sid") if request.auth is not None else None
        sessions = UserSession.objects.filter(user=request.user, device__installation_id=values["installation_id"], device__is_active=True, revoked_at__isnull=True, expires_at__gt=timezone.now())
        if not sid or not sessions.filter(pk=sid).exists():
            raise PermissionDenied("حدث الجلسة قبل تسجيل جهاز الإشعارات.")
        try:
            binding = register_device(request.user, values["installation_id"], values["fcm_token"], session_id=sid)
        except (DjangoValidationError, IntegrityError):
            raise serializers.ValidationError("تعذر تسجيل جهاز الإشعارات.") from None
        return success_response({"registered": True, "active": binding.active})

    def delete(self, request):
        installation_id = request.headers.get("X-Installation-Id", "")
        PushDevice.objects.filter(device__user=request.user, installation_id=installation_id).update(active=False)
        return success_response({"active": False})
