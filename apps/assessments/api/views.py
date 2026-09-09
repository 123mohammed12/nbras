from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from apps.common.api import success_response, error_response
from apps.assessments.models import Assessment
from apps.assessments.api.serializers import AssessmentSerializer


class AssessmentListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="جلب قائمة الاختبارات المنشورة مفلترة بالهيكل الأكاديمي",
        parameters=[
            OpenApiParameter("subject_id", OpenApiTypes.UUID, description="مُعرّف المادة"),
            OpenApiParameter("unit_id", OpenApiTypes.UUID, description="مُعرّف الوحدة"),
            OpenApiParameter("lesson_id", OpenApiTypes.UUID, description="مُعرّف الدرس"),
        ],
        responses={200: AssessmentSerializer(many=True)},
    )
    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        unit_id = request.query_params.get("unit_id")
        lesson_id = request.query_params.get("lesson_id")

        qs = Assessment.objects.filter(status="published")
        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)

        serializer = AssessmentSerializer(qs, many=True)
        return success_response(data=serializer.data)


class AssessmentDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="جلب تفاصيل اختبار محدد",
        responses={200: AssessmentSerializer},
    )
    def get(self, request, pk):
        assessment = Assessment.objects.filter(id=pk, status="published").first()
        if not assessment:
            return error_response(code="NOT_FOUND", message="الاختبار غير موجود.", status=404)

        serializer = AssessmentSerializer(assessment)
        return success_response(data=serializer.data)
