from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser
from drf_spectacular.utils import extend_schema
from apps.common.api import success_response, error_response
from apps.common.pagination import StandardPagination
from apps.question_bank.models import Question
from apps.question_bank.api.serializers import QuestionAdminSerializer


class QuestionAdminListAPIView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(responses={200: QuestionAdminSerializer(many=True)})
    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        unit_id = request.query_params.get("unit_id")
        lesson_id = request.query_params.get("lesson_id")
        source_type = request.query_params.get("source_type")

        qs = Question.objects.select_related(
            "current_version", "subject", "unit", "lesson"
        ).prefetch_related(
            "current_version__options", "current_version__assets"
        ).all()

        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        if source_type:
            qs = qs.filter(source_type=source_type)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = QuestionAdminSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class QuestionAdminDetailAPIView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(responses={200: QuestionAdminSerializer})
    def get(self, request, pk):
        question = Question.objects.filter(id=pk).select_related(
            "current_version", "subject", "unit", "lesson"
        ).prefetch_related(
            "current_version__options", "current_version__assets"
        ).first()

        if not question:
            return error_response(message="السؤال غير موجود.", status_code=404)

        serializer = QuestionAdminSerializer(question)
        return success_response(data=serializer.data)
