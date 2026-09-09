"""
Locations API Views with Pagination, Throttling, and OpenAPI schemas.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.common.api import error_response, success_response
from apps.common.pagination import StandardPagination
from apps.locations.models import District, Governorate, Isolation, School
from apps.locations.serializers import (
    DistrictSerializer,
    GovernorateSerializer,
    IsolationSerializer,
    SchoolSerializer,
)


class LocationsPublicReadThrottle(SimpleRateThrottle):
    scope = "locations_public_read"
    rate = "120/minute"

    def get_cache_key(self, request, view):
        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            ident = f"user_{request.user.id}"
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class GovernorateListAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LocationsPublicReadThrottle]

    @extend_schema(
        responses={200: GovernorateSerializer(many=True)},
        summary="قائمة المحافظات اليمنية الفعالة",
        tags=["Locations"],
    )
    def get(self, request, *args, **kwargs):
        qs = Governorate.objects.filter(is_active=True).order_by("sort_order", "name_ar")
        serializer = GovernorateSerializer(qs, many=True)
        return success_response(data=serializer.data)


class DistrictListAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LocationsPublicReadThrottle]

    @extend_schema(
        parameters=[
            OpenApiParameter("governorate_id", type=int, description="المعرف الرقمي للمحافظة"),
        ],
        responses={200: DistrictSerializer(many=True)},
        summary="قائمة المديريات المفلترة بالمحافظة",
        tags=["Locations"],
    )
    def get(self, request, *args, **kwargs):
        qs = District.objects.filter(is_active=True).select_related("governorate")
        gov_id = request.query_params.get("governorate_id")
        if gov_id:
            qs = qs.filter(governorate_id=gov_id)
        qs = qs.order_by("sort_order", "name_ar")
        serializer = DistrictSerializer(qs, many=True)
        return success_response(data=serializer.data)


class IsolationListAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LocationsPublicReadThrottle]

    @extend_schema(
        parameters=[
            OpenApiParameter("district_id", type=int, description="المعرف الرقمي للمديرية"),
        ],
        responses={200: IsolationSerializer(many=True)},
        summary="قائمة العزل المفلترة بالمديرية",
        tags=["Locations"],
    )
    def get(self, request, *args, **kwargs):
        qs = Isolation.objects.filter(is_active=True).select_related("district")
        dist_id = request.query_params.get("district_id")
        if dist_id:
            qs = qs.filter(district_id=dist_id)
        qs = qs.order_by("sort_order", "name_ar")
        serializer = IsolationSerializer(qs, many=True)
        return success_response(data=serializer.data)


class SchoolListAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LocationsPublicReadThrottle]
    pagination_class = StandardPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("governorate_id", type=int, description="معرف المحافظة"),
            OpenApiParameter("district_id", type=int, description="معرف المديرية"),
            OpenApiParameter("isolation_id", type=int, description="معرف العزلة"),
            OpenApiParameter("school_type", type=str, description="نوع المدرسة: public أو private"),
            OpenApiParameter("gender_type", type=str, description="جنس المدرسة: boys, girls, mixed"),
            OpenApiParameter("q", type=str, description="بحث برغم أو اسم المدرسة بالعربي (حد أقصى 100 محرف)"),
            OpenApiParameter("page", type=int, description="رقم الصفحة"),
            OpenApiParameter("page_size", type=int, description="عدد العناصر بالصفحة (1-100)"),
        ],
        responses={200: SchoolSerializer(many=True)},
        summary="البحث وقائمة المدارس (مقسمة لصفحات)",
        tags=["Locations"],
    )
    def get(self, request, *args, **kwargs):
        qs = School.objects.filter(is_active=True).select_related(
            "governorate", "district", "isolation"
        )

        gov_id = request.query_params.get("governorate_id")
        dist_id = request.query_params.get("district_id")
        iso_id = request.query_params.get("isolation_id")
        school_type = request.query_params.get("school_type")
        gender_type = request.query_params.get("gender_type")
        q = request.query_params.get("q") or request.query_params.get("search")

        if gov_id:
            qs = qs.filter(governorate_id=gov_id)
        if dist_id:
            qs = qs.filter(district_id=dist_id)
        if iso_id:
            qs = qs.filter(isolation_id=iso_id)
        if school_type:
            qs = qs.filter(school_type=school_type)
        if gender_type:
            qs = qs.filter(gender_type=gender_type)

        if q:
            q_clean = q.strip()
            if len(q_clean) > 100:
                return error_response(
                    message="نص البحث طويل جداً (الحد الأقصى 100 محرف).",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(name_ar__icontains=q_clean)

        qs = qs.order_by("name_ar")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = SchoolSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = SchoolSerializer(qs, many=True)
        return success_response(data=serializer.data)
