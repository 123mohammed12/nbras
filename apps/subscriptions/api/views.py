from django.db import models
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.common.api import error_response, success_response
from apps.curriculum.models import AcademicYear, ContentStatus, StudyEnrollment, Subject
from apps.entitlements.models import FreeAccessPolicy
from apps.entitlements.services.access_service import check_resource_access
from apps.subscriptions.api.serializers import (
    AccessCheckQuerySerializer, ActivationCodeRequestSerializer,
    RedeemRequestSerializer, SubscriptionPlanSerializer, SubscriptionSerializer,
)
from apps.subscriptions.models import PackageTierType, Subscription, SubscriptionPlan, SubscriptionStatus
from apps.subscriptions.services.redeem_service import preview_activation_code, redeem_activation_code
from apps.subscriptions.throttles import RedeemBurstRateThrottle, RedeemSustainedRateThrottle
from apps.subscriptions.services.access_overview import access_overview


def _enrollment(request):
    if not request.user or not request.user.is_authenticated:
        return None
    return StudyEnrollment.objects.filter(user=request.user, is_active=True).select_related("academic_year", "grade", "section").first()


def _active_subscription(request, enrollment):
    if not enrollment:
        return None
    return Subscription.objects.filter(
        user=request.user, study_enrollment=enrollment,
        status=SubscriptionStatus.ACTIVE,
        starts_at__lte=timezone.now(),
        expires_at__gt=timezone.now(),
    ).select_related("plan", "academic_year").prefetch_related("selected_subjects").first()


class SubscriptionCatalogAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        enrollment = _enrollment(request)
        year = enrollment.academic_year if enrollment else AcademicYear.objects.filter(status=AcademicYear.Status.ACTIVE).first()
        plans = SubscriptionPlan.objects.filter(is_active=True, is_catalog_visible=True)
        if year:
            plans = plans.filter(academic_year=year)
        subjects = Subject.objects.none()
        if enrollment:
            plans = plans.filter(grade=enrollment.grade, section=enrollment.section)
            subjects = Subject.objects.filter(
                grade=enrollment.grade, section=enrollment.section,
                status=ContentStatus.PUBLISHED,
            ).order_by("sort_order", "id")
            count = subjects.count()
            plans = plans.filter(
                models.Q(tier_type=PackageTierType.ALL_SUBJECTS)
                | models.Q(subject_limit__lte=count)
            )
        plans = plans.select_related("academic_year", "grade", "section").prefetch_related("plan_entitlements__entitlement")
        subscription = _active_subscription(request, enrollment)
        free, overview, latest = access_overview(request.user, enrollment)
        return success_response(data={
            "access_overview": overview,
            "latest_subscription": SubscriptionSerializer(latest).data if latest else None,
            "academic_year": ({"code": year.code, "name": year.name_ar, "ends_at": year.ends_at} if year else None),
            "includes_both_terms": True,
            "free_access": free,
            "subjects": [{"id": str(item.id), "name": item.name_ar} for item in subjects],
            "current_subscription": SubscriptionSerializer(subscription).data if subscription else None,
            "plans": SubscriptionPlanSerializer(plans, many=True).data,
            "acquisition": {"activation_code": True, "external_payment": False},
        })


class SubscriptionPlanListAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        response = SubscriptionCatalogAPIView().get(request)
        return response


class MySubscriptionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        enrollment = _enrollment(request)
        if not enrollment:
            return error_response(message="لا يوجد ملف دراسي نشط.", status_code=400)
        subscription = _active_subscription(request, enrollment)
        return success_response(data={
            "has_active_subscription": subscription is not None,
            "subscription": SubscriptionSerializer(subscription).data if subscription else None,
        })


class MySubscriptionsListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Subscription.objects.filter(user=request.user).select_related("plan", "academic_year").prefetch_related("selected_subjects").order_by("-created_at")
        return success_response(data=SubscriptionSerializer(rows, many=True).data)


class PreviewActivationCodeAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [RedeemBurstRateThrottle, RedeemSustainedRateThrottle]

    def post(self, request):
        serializer = ActivationCodeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = _enrollment(request)
        preview = preview_activation_code(
            user=request.user, enrollment=enrollment,
            raw_code=serializer.validated_data["code"],
            selected_subject_ids=serializer.validated_data["subject_ids"],
        )
        return success_response(data=preview)


class RedeemActivationCodeAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [RedeemBurstRateThrottle, RedeemSustainedRateThrottle]

    def post(self, request):
        serializer = RedeemRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = _enrollment(request)
        subscription, meta = redeem_activation_code(
            user=request.user, enrollment=enrollment,
            raw_code=serializer.validated_data["code"],
            selected_subject_ids=serializer.validated_data["subject_ids"],
            idempotency_key=request.META.get("HTTP_IDEMPOTENCY_KEY") or serializer.validated_data.get("client_request_id"),
            request_id=request.META.get("HTTP_X_REQUEST_ID"),
        )
        return success_response(data={
            **meta,
            "subscription": SubscriptionSerializer(subscription).data,
        })


class CheckResourceAccessAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = AccessCheckQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        decision = check_resource_access(
            user=request.user, enrollment=_enrollment(request),
            resource_type=serializer.validated_data["resource_type"],
            resource_id=serializer.validated_data["resource_id"],
        )
        return success_response(data=decision.to_dict())
