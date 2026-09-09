from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from apps.common.api import success_response, error_response
from apps.common.exceptions import ApplicationError
from apps.attempts.models import AssessmentAttempt, AttemptQuestion, AttemptAnswer
from apps.attempts.api.serializers import (
    AssessmentAttemptSerializer,
    AttemptQuestionSerializer,
    AttemptResultSerializer,
    AttemptStartRequestSerializer,
    AssessmentSourceStartRequestSerializer,
    AttemptSaveAnswerRequestSerializer,
    AttemptSubmitRequestSerializer,
    PracticeAnswerResponseSerializer,
    ExamAnswerResponseSerializer,
    CustomTestSpecSerializer,
    CustomTestCreateSerializer,
    CustomTestNewSameSettingsSerializer,
    MockStartSerializer,
    PracticeScopeSerializer,
    WrongPracticeCreateSerializer,
    WeaknessPracticeCreateSerializer,
)
from apps.attempts.services.attempt_service import (
    start_assessment_attempt,
    save_attempt_answer,
    submit_assessment_attempt,
    get_attempt_review,
    create_wrong_answers_attempt,
    create_retry_attempt,
    get_authoritative_attempt,
)
from apps.attempts.services.assessment_entry import (
    get_assessment_entry,
    start_from_source,
)
from uuid import UUID
from apps.common.idempotency import idempotent_view

from apps.assessments.models import TrainingBatchScope
from apps.assessments.services.training import training_batch_cards
from apps.curriculum.models import StudyEnrollment
from apps.entitlements.services.access_service import check_resource_access
from apps.attempts.services.custom_tests import (
    custom_builder_configuration,
    preview_custom_test,
    create_custom_test,
    new_custom_test_with_same_settings,
)
from apps.attempts.services.mock_exams import (
    get_mock_blueprint,
    list_mock_blueprints,
    start_mock,
)
from apps.attempts.services.ar06_practice import (
    create_global_wrong_practice,
    create_weakness_practice,
    weakness_signals,
    wrong_answer_summary,
)


class MockBlueprintListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        if not subject_id:
            raise ApplicationError("subject_id is required.", code="INVALID_SCOPE")
        return success_response(data=list_mock_blueprints(
            user=request.user, subject_id=subject_id,
        ))


class MockBlueprintDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, blueprint_id):
        return success_response(data=get_mock_blueprint(
            user=request.user, blueprint_id=str(blueprint_id),
        ))


class MockBlueprintStartAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=MockStartSerializer, responses={201: AssessmentAttemptSerializer})
    def post(self, request, blueprint_id):
        serializer = MockStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = (
            serializer.validated_data.get("idempotency_key")
            or request.META.get("HTTP_IDEMPOTENCY_KEY")
        )
        attempt = start_mock(
            user=request.user, blueprint_id=str(blueprint_id),
            idempotency_key=idempotency_key,
        )
        return success_response(data=AssessmentAttemptSerializer(attempt).data, status=201)


class CustomTestConfigurationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        if not subject_id:
            raise ApplicationError("subject_id is required.", code="INVALID_SCOPE")
        return success_response(data=custom_builder_configuration(
            user=request.user, subject_id=subject_id,
        ))


class CustomTestPreviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=CustomTestSpecSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = CustomTestSpecSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        preview = preview_custom_test(
            user=request.user, payload=serializer.validated_data,
        )
        # FE-08 keeps bank capacity hidden from learner-facing contracts.
        return success_response(data={
            "requested_count": preview["requested_count"],
            "can_create_exact": preview["can_create_exact"],
            "reason_code": (
                None if preview["can_create_exact"] else "QUESTION_POOL_EXHAUSTED"
            ),
        })


class CustomTestCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=CustomTestCreateSerializer, responses={201: AssessmentAttemptSerializer})
    def post(self, request):
        serializer = CustomTestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.pop("allow_available", False)  # accepted only for old clients; never applied
        idempotency_key = values.pop("idempotency_key", None) or request.META.get("HTTP_IDEMPOTENCY_KEY")
        attempt = create_custom_test(
            user=request.user, payload=values,
            allow_available=False, idempotency_key=idempotency_key,
        )
        return success_response(data=AssessmentAttemptSerializer(attempt).data, status=201)


class CustomTestNewSameSettingsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=CustomTestNewSameSettingsSerializer, responses={201: AssessmentAttemptSerializer})
    def post(self, request, pk):
        serializer = CustomTestNewSameSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = new_custom_test_with_same_settings(
            user=request.user, parent_attempt_id=str(pk),
            idempotency_key=serializer.validated_data.get("idempotency_key") or request.META.get("HTTP_IDEMPOTENCY_KEY"),
        )
        return success_response(data=AssessmentAttemptSerializer(attempt).data, status=201)


class AssessmentEntryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[
        OpenApiParameter(
            name="exam_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Exact historical model for a unit-ministerial subset.",
        ),
        OpenApiParameter(
            name="part",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Stable part number when an unusually large model subset is split.",
        ),
    ])
    def get(self, request, source_kind, source_id):
        year = _source_year(request.query_params.get("year"), source_kind)
        batch_index = _source_batch(
            request.query_params.get("batch"), source_kind,
        )
        exam_id = _source_exam_id(
            request.query_params.get("exam_id"), source_kind
        )
        part_index = _source_part(
            request.query_params.get("part"), source_kind
        )
        return success_response(data=get_assessment_entry(
            user=request.user, source_kind=source_kind, source_id=source_id,
            year=year, batch_index=batch_index, exam_id=exam_id,
            part_index=part_index,
        ))


class StartAssessmentSourceAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=AssessmentSourceStartRequestSerializer)
    def post(self, request, source_kind, source_id):
        year = _source_year(request.data.get("year"), source_kind)
        batch_index = _source_batch(request.data.get("batch"), source_kind)
        exam_id = _source_exam_id(request.data.get("exam_id"), source_kind)
        part_index = _source_part(request.data.get("part"), source_kind)
        attempt = start_from_source(
            user=request.user,
            source_kind=source_kind,
            source_id=source_id,
            year=year,
            batch_index=batch_index,
            exam_id=exam_id,
            part_index=part_index,
            idempotency_key=request.data.get("idempotency_key") or request.META.get("HTTP_IDEMPOTENCY_KEY"),
        )
        return success_response(data=AssessmentAttemptSerializer(attempt).data, status=201)


class SubjectTrainingBatchesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, source_id):
        enrollment = StudyEnrollment.objects.filter(
            user=request.user, is_active=True
        ).first()
        if enrollment is None:
            raise ApplicationError("No active enrollment.", code="NO_ACTIVE_ENROLLMENT")
        decision = check_resource_access(
            user=request.user,
            enrollment=enrollment,
            resource_type="subject",
            resource_id=source_id,
        )
        if not decision.allowed:
            raise ApplicationError(
                "Subject Training requires full subject access.",
                code="SUBSCRIPTION_REQUIRED",
            )
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(30, max(1, int(request.query_params.get("page_size", 20))))
        except (TypeError, ValueError):
            raise ApplicationError(
                "Invalid Training pagination.", code="INVALID_PAGINATION"
            )
        cards, total, covered, batch_count = training_batch_cards(
            user=request.user,
            enrollment=enrollment,
            scope_type=TrainingBatchScope.SUBJECT,
            source_id=source_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            prioritize=False,
        )
        return success_response(
            data={
                "results": cards,
                "page": page,
                "page_size": page_size,
                "count": batch_count,
                "has_next": page * page_size < batch_count,
                "total_questions_count": total,
                "covered_questions_count": covered,
            }
        )


def _source_year(raw_year, source_kind):
    if raw_year in (None, ""):
        return None
    if source_kind != "unit_ministerial":
        raise ApplicationError(
            "Year is only supported for unit ministerial tests.",
            code="INVALID_ASSESSMENT_YEAR",
        )
    try:
        year = int(raw_year)
    except (TypeError, ValueError):
        raise ApplicationError(
            "Year must be a valid number.", code="INVALID_ASSESSMENT_YEAR"
        )
    if year < 1900 or year > 2200:
        raise ApplicationError(
            "Year is outside the supported range.",
            code="INVALID_ASSESSMENT_YEAR",
        )
    return year


def _source_batch(raw_batch, source_kind):
    if raw_batch in (None, ""):
        return None
    if source_kind not in {
        "lesson_ministerial",
        "lesson_training",
        "unit_training",
        "subject_training",
    }:
        raise ApplicationError(
            "Batch is not supported for this assessment source.",
            code="INVALID_ASSESSMENT_BATCH",
        )
    try:
        batch_index = int(raw_batch)
    except (TypeError, ValueError):
        raise ApplicationError(
            "Batch must be a valid number.", code="INVALID_ASSESSMENT_BATCH"
        )
    if batch_index < 1:
        raise ApplicationError(
            "Batch must be positive.", code="INVALID_ASSESSMENT_BATCH"
        )
    return batch_index


def _source_exam_id(raw_exam_id, source_kind):
    if raw_exam_id in (None, ""):
        return None
    if source_kind != "unit_ministerial":
        raise ApplicationError(
            "Historical model is only supported for unit ministerial tests.",
            code="INVALID_MINISTERIAL_MODEL",
        )
    try:
        return str(UUID(str(raw_exam_id)))
    except (TypeError, ValueError, AttributeError):
        raise ApplicationError(
            "Historical model must be a valid identifier.",
            code="INVALID_MINISTERIAL_MODEL",
        )


def _source_part(raw_part, source_kind):
    if raw_part in (None, ""):
        return None
    if source_kind != "unit_ministerial":
        raise ApplicationError(
            "Part is only supported for unit ministerial tests.",
            code="INVALID_ASSESSMENT_PART",
        )
    try:
        part = int(raw_part)
    except (TypeError, ValueError):
        raise ApplicationError(
            "Part must be a valid number.", code="INVALID_ASSESSMENT_PART"
        )
    if part < 1:
        raise ApplicationError(
            "Part must be positive.", code="INVALID_ASSESSMENT_PART"
        )
    return part


class StartAssessmentAttemptAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="بدء محاولة اختبار جديدة",
        request=AttemptStartRequestSerializer,
        responses={201: AssessmentAttemptSerializer},
    )
    def post(self, request, assessment_id):
        mode = request.data.get("mode", "exam")
        shuffle_q = request.data.get("shuffle_questions")
        shuffle_o = request.data.get("shuffle_options")
        client_attempt_id = request.data.get("client_attempt_id")
        idempotency_key = request.data.get("idempotency_key") or request.META.get("HTTP_IDEMPOTENCY_KEY")

        attempt = start_assessment_attempt(
            user=request.user,
            assessment_id=str(assessment_id),
            mode=mode,
            shuffle_questions=shuffle_q,
            shuffle_options=shuffle_o,
            client_attempt_id=client_attempt_id,
            idempotency_key=idempotency_key,
        )
        serializer = AssessmentAttemptSerializer(attempt)
        return success_response(data=serializer.data, status=201)



class AttemptDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="جلب تفاصيل المحاولة والحالة",
        responses={200: AssessmentAttemptSerializer},
    )
    def get(self, request, pk):
        attempt = get_authoritative_attempt(attempt_id=str(pk), user=request.user)
        if not attempt:
            return error_response(code="NOT_FOUND", message="المحاولة غير موجودة.", status=404)

        serializer = AssessmentAttemptSerializer(attempt)
        return success_response(data=serializer.data)


class AttemptRetryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        attempt = create_retry_attempt(parent_attempt_id=str(pk), user=request.user)
        return success_response(data=AssessmentAttemptSerializer(attempt).data, status=201)


class AttemptQuestionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="جلب أسئلة المحاولة وتفاصيل الاستئناف",
        responses={200: AttemptQuestionSerializer(many=True)},
    )
    def get(self, request, pk):
        attempt = AssessmentAttempt.objects.filter(id=pk, user=request.user).first()
        if not attempt:
            return error_response(code="NOT_FOUND", message="المحاولة غير موجودة.", status=404)


        questions = list(
            AttemptQuestion.objects.filter(attempt=attempt)
            .select_related("attempt")
            .order_by("sort_order")
        )
        
        # Batch fetch all answers for these questions to avoid N+1 queries
        answers = AttemptAnswer.objects.filter(attempt=attempt, attempt_question__in=questions)
        self._answers_map = {ans.attempt_question_id: ans for ans in answers}

        serializer = AttemptQuestionSerializer(questions, many=True, context={"view": self})
        return success_response(data=serializer.data)


class AttemptSaveAnswerAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="حفظ إجابة سؤال (تدريب أو اختبار)",
        request=AttemptSaveAnswerRequestSerializer,
        responses={200: PracticeAnswerResponseSerializer},
    )
    @idempotent_view
    def post(self, request, pk):
        request_serializer = AttemptSaveAnswerRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        values = request_serializer.validated_data
        attempt_question_id = values.get("attempt_question_id")
        answer_payload = values.get("answer", {})
        selected_option_id = values.get("selected_option_id")
        selected_option_key = values.get("selected_option_key")
        answer_text = values.get("answer_text")
        is_flagged = values.get("is_flagged", False)
        response_time = values.get("response_time_seconds", 0)

        if not attempt_question_id:
            return error_response(code="BAD_REQUEST", message="attempt_question_id مطلوب.", status=400)


        answer, response_data = save_attempt_answer(
            attempt_id=str(pk),
            attempt_question_id=str(attempt_question_id),
            user=request.user,
            answer_payload=answer_payload,
            selected_option_id=selected_option_id,
            selected_option_key=selected_option_key,
            answer_text=answer_text,
            is_flagged=is_flagged,
            response_time_seconds=response_time,
            client_revision=values.get("client_revision", 0),
            expected_revision=values.get("expected_revision"),
            expected_answer_revision=values.get("expected_answer_revision"),
            is_visited=values.get("is_visited", True),
            # Calls predating contract v1 implicitly checked practice answers.
            # New clients send evaluate=false on selection and true on Check.
            evaluate=request.data.get("evaluate", True),
        )
        return success_response(data=response_data)


class AttemptSubmitAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="تسليم المحاولة وتصحيحها نهائياً",
        request=AttemptSubmitRequestSerializer,
        responses={200: AttemptResultSerializer},
    )
    @idempotent_view
    def post(self, request, pk):
        request_serializer = AttemptSubmitRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        values = request_serializer.validated_data
        attempt = submit_assessment_attempt(
            attempt_id=str(pk),
            user=request.user,
            final_answers=values.get("answers", []),
            submission_reason=values.get("submission_reason", "manual"),
            expected_revision=values.get("expected_revision"),
            final_frozen_at=values.get("final_frozen_at"),
        )
        serializer = AttemptResultSerializer(attempt)
        return success_response(data=serializer.data)


class AttemptResultAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="جلب نتيجة وتحليل المحاولة بعد التسليم",
        responses={200: AttemptResultSerializer},
    )
    def get(self, request, pk):
        attempt = AssessmentAttempt.objects.filter(id=pk, user=request.user).select_related("assessment", "analysis").first()
        if not attempt:
            return error_response(code="NOT_FOUND", message="المحاولة غير موجودة.", status=404)

        serializer = AttemptResultSerializer(attempt)
        return success_response(data=serializer.data)


class AttemptReviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="مراجعة تفصيلية لجميع الأسئلة والإجابات الصحيحة بعد التسليم",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, pk):
        review_data = get_attempt_review(attempt_id=str(pk), user=request.user)
        return success_response(data=review_data)


class AttemptRetryWrongAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="بدء محاولة جديدة لإعادة الأسئلة الخاطئة فقط",
        request=None,
        responses={201: AssessmentAttemptSerializer},
    )
    def post(self, request, pk):
        new_attempt = create_wrong_answers_attempt(parent_attempt_id=str(pk), user=request.user)
        serializer = AssessmentAttemptSerializer(new_attempt)
        return success_response(data=serializer.data, status=201)


class WrongAnswerSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = PracticeScopeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            limit = int(request.query_params.get("limit", 20))
        except (TypeError, ValueError):
            raise ApplicationError("limit is invalid.", code="WRONG_PRACTICE_INVALID")
        return success_response(data=wrong_answer_summary(
            user=request.user,
            subject_id=values["subject_id"],
            unit_id=values.get("unit_id"),
            lesson_id=values.get("lesson_id"),
            limit=limit,
        ))


class WrongPracticeCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=WrongPracticeCreateSerializer, responses={201: AssessmentAttemptSerializer})
    def post(self, request):
        serializer = WrongPracticeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        attempt = create_global_wrong_practice(user=request.user, **values)
        return success_response(data=AssessmentAttemptSerializer(attempt).data, status=201)


class WeaknessSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = PracticeScopeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return success_response(data=weakness_signals(
            user=request.user, **serializer.validated_data,
        ))


class WeaknessPracticeCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=WeaknessPracticeCreateSerializer, responses={201: AssessmentAttemptSerializer})
    def post(self, request):
        serializer = WeaknessPracticeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = create_weakness_practice(
            user=request.user, **serializer.validated_data,
        )
        return success_response(data=AssessmentAttemptSerializer(attempt).data, status=201)



class MyAttemptsListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="سجل محاولات المستخدم الحالي",
        responses={200: AssessmentAttemptSerializer(many=True)},
    )
    def get(self, request):
        attempts = AssessmentAttempt.objects.filter(user=request.user).select_related("assessment").order_by("-created_at")[:50]
        serializer = AssessmentAttemptSerializer(attempts, many=True)
        return success_response(data=serializer.data)
