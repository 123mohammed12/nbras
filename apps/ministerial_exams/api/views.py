from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from apps.common.api import success_response, error_response
from apps.common.pagination import StandardPagination
from apps.curriculum.models import StudyEnrollment
from apps.ministerial_exams.models import MinisterialExam
from apps.ministerial_exams.api.serializers import (
    MinisterialExamListSerializer,
    MinisterialExamDetailSerializer,
)
from apps.entitlements.services.access_service import check_resources_access_batch, check_resource_access


class MinisterialExamListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MinisterialExamListSerializer(many=True)})
    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        year = request.query_params.get("year")
        exam_role = request.query_params.get("exam_role")
        model_number = request.query_params.get("model_number")

        qs = MinisterialExam.objects.filter(status="published").select_related("subject", "subject__grade", "subject__section")

        # Enrollment filtering if non-staff student user
        if not (request.user.is_staff or getattr(request.user, "is_superuser", False)):
            active_enrollment = StudyEnrollment.objects.filter(user=request.user, is_active=True).first()
            if active_enrollment:
                qs = qs.filter(
                    subject__grade=active_enrollment.grade,
                    subject__section=active_enrollment.section,
                )

        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        if year:
            qs = qs.filter(exam_year=year)
        if exam_role:
            qs = qs.filter(exam_role=exam_role)
        if model_number:
            qs = qs.filter(model_number=model_number)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        decisions = check_resources_access_batch(
            user=request.user,
            enrollment=StudyEnrollment.objects.filter(user=request.user, is_active=True).first(),
            resources=[{"type": "ministerial_exam", "id": str(item.id)} for item in page],
        )
        for item in page:
            item._access_decision = decisions[("ministerial_exam", str(item.id))]
        serializer = MinisterialExamListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class MinisterialExamDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MinisterialExamDetailSerializer})
    def get(self, request, pk):
        exam = MinisterialExam.objects.filter(id=pk, status="published").select_related("subject", "subject__grade", "subject__section").first()
        if not exam:
            return error_response(message="النموذج الوزاري غير موجود.", status_code=404)

        if not (request.user.is_staff or getattr(request.user, "is_superuser", False)):
            active_enrollment = StudyEnrollment.objects.filter(user=request.user, is_active=True).first()
            if active_enrollment:
                if exam.subject.grade_id != active_enrollment.grade_id or exam.subject.section_id != active_enrollment.section_id:
                    return error_response(message="النموذج الوزاري غير متاح لصفك وقسمك الدراسي الحالي.", status_code=403)

        exam._access_decision = check_resource_access(
            user=request.user,
            enrollment=StudyEnrollment.objects.filter(user=request.user, is_active=True).first(),
            resource_type="ministerial_exam", resource_id=str(exam.id),
        )
        serializer = MinisterialExamDetailSerializer(exam)
        return success_response(data=serializer.data)
