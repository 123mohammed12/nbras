from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from apps.common.api import success_response, error_response
from apps.progress.models import SubjectProgress, UnitProgress, LessonProgress
from apps.progress.services.progress_selectors import get_progress_overview
from apps.progress.services.session_tracking import start_learning_session, heartbeat_learning_session, finish_learning_session
from apps.progress.services.resource_tracking import (
    start_learning_resource,
    complete_learning_resource,
    update_learning_resource_progress,
)
from apps.progress.api.serializers import (
    ProgressOverviewSerializer,
    ProgressDetailSerializer,
    AssessmentHistoryItemSerializer,
    SubjectProgressSerializer,
    UnitProgressSerializer,
    LessonProgressSerializer,
    SessionStartRequestSerializer,
    ClientEventRequestSerializer,
    ResourceProgressUpdateRequestSerializer,
    LearningSessionSerializer,
    LearningResourceProgressSerializer,
)
from apps.progress.services.aggregation import (
    completed_attempt_history,
    get_active_enrollment,
    lesson_progress_details,
    progress_overview,
    subject_progress_details,
    unit_progress_details,
    _attempt_summary,
)
from apps.common.pagination import StandardPagination


class ProgressOverviewAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProgressOverviewSerializer

    @extend_schema(responses={200: ProgressOverviewSerializer})
    def get(self, request):
        enrollment = getattr(request, "study_enrollment", None) or get_active_enrollment(request.user)
        if enrollment is None:
            return error_response(code="NO_ACTIVE_ENROLLMENT", message="لا يوجد ملف دراسي نشط.", status=404)
        data = progress_overview(user=request.user, enrollment=enrollment)
        serializer = self.get_serializer(data)
        return success_response(data=serializer.data)


class SubjectProgressDetailAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProgressDetailSerializer

    @extend_schema(responses={200: SubjectProgressSerializer})
    def get(self, request, id):
        enrollment = getattr(request, "study_enrollment", None) or get_active_enrollment(request.user)
        if enrollment is None:
            return error_response(code="NO_ACTIVE_ENROLLMENT", message="لا يوجد ملف دراسي نشط.", status=404)
        data, error = subject_progress_details(user=request.user, enrollment=enrollment, subject_id=id)
        return _detail_response(self, data, error)


class UnitProgressDetailAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProgressDetailSerializer

    @extend_schema(responses={200: UnitProgressSerializer})
    def get(self, request, id):
        enrollment = getattr(request, "study_enrollment", None) or get_active_enrollment(request.user)
        if enrollment is None:
            return error_response(code="NO_ACTIVE_ENROLLMENT", message="لا يوجد ملف دراسي نشط.", status=404)
        data, error = unit_progress_details(user=request.user, enrollment=enrollment, unit_id=id)
        return _detail_response(self, data, error)


class LessonProgressDetailAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProgressDetailSerializer

    @extend_schema(responses={200: LessonProgressSerializer})
    def get(self, request, id):
        enrollment = getattr(request, "study_enrollment", None) or get_active_enrollment(request.user)
        if enrollment is None:
            return error_response(code="NO_ACTIVE_ENROLLMENT", message="لا يوجد ملف دراسي نشط.", status=404)
        data, error = lesson_progress_details(user=request.user, enrollment=enrollment, lesson_id=id)
        return _detail_response(self, data, error)


def _detail_response(view, data, error):
    if error == "denied":
        return error_response(code="ACCESS_DENIED", message="هذا المحتوى غير متاح ضمن خطتك.", status=403)
    if error:
        return error_response(code="NOT_FOUND", message="النطاق الدراسي غير موجود.", status=404)
    return success_response(data=view.get_serializer(data).data)


class AssessmentHistoryAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AssessmentHistoryItemSerializer
    pagination_class = StandardPagination

    @extend_schema(responses={200: AssessmentHistoryItemSerializer(many=True)})
    def get(self, request):
        enrollment = getattr(request, "study_enrollment", None) or get_active_enrollment(request.user)
        if enrollment is None:
            return error_response(code="NO_ACTIVE_ENROLLMENT", message="لا يوجد ملف دراسي نشط.", status=404)
        category = request.query_params.get("category")
        if category not in (None, "all", "ministerial", "other"):
            return error_response(code="INVALID_FILTER", message="مرشح السجل غير صالح.", status=422)
        queryset = completed_attempt_history(
            user=request.user,
            enrollment=enrollment,
            category=None if category in (None, "all") else category,
            subject_id=request.query_params.get("subject_id"),
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        data = [_attempt_summary(attempt) for attempt in page]
        serializer = self.get_serializer(data, many=True)
        return paginator.get_paginated_response(serializer.data)




class SessionStartAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SessionStartRequestSerializer

    @extend_schema(request=SessionStartRequestSerializer, responses={200: LearningSessionSerializer})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        session = start_learning_session(
            user=request.user,
            resource_type=data["resource_type"],
            resource_id=data["resource_id"],
            client_session_id=data["client_session_id"],
        )
        return success_response(data=LearningSessionSerializer(session).data)


class SessionHeartbeatAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClientEventRequestSerializer

    @extend_schema(request=ClientEventRequestSerializer, responses={200: LearningSessionSerializer})
    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        session = heartbeat_learning_session(
            user=request.user,
            client_session_id=pk,
        )
        return success_response(data=LearningSessionSerializer(session).data)


class SessionFinishAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClientEventRequestSerializer

    @extend_schema(request=ClientEventRequestSerializer, responses={200: LearningSessionSerializer})
    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        session = finish_learning_session(
            user=request.user,
            client_session_id=pk,
        )
        return success_response(data=LearningSessionSerializer(session).data)


class ResourceStartAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClientEventRequestSerializer

    @extend_schema(request=ClientEventRequestSerializer, responses={200: LearningResourceProgressSerializer})
    def post(self, request, resource_type, resource_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        prog = start_learning_resource(
            user=request.user,
            resource_type=resource_type,
            resource_id=resource_id,
            client_event_id=serializer.validated_data.get("client_event_id")
        )
        return success_response(data=LearningResourceProgressSerializer(prog).data)


class ResourceCompleteAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClientEventRequestSerializer

    @extend_schema(request=ClientEventRequestSerializer, responses={200: LearningResourceProgressSerializer})
    def post(self, request, resource_type, resource_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        prog = complete_learning_resource(
            user=request.user,
            resource_type=resource_type,
            resource_id=resource_id,
            client_event_id=serializer.validated_data.get("client_event_id")
        )
        return success_response(data=LearningResourceProgressSerializer(prog).data)


class ResourceProgressAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ResourceProgressUpdateRequestSerializer

    @extend_schema(
        request=ResourceProgressUpdateRequestSerializer,
        responses={200: LearningResourceProgressSerializer},
    )
    def put(self, request, resource_type, resource_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        prog = update_learning_resource_progress(
            user=request.user,
            resource_type=resource_type,
            resource_id=resource_id,
            completion_percentage=serializer.validated_data["completion_percentage"],
            last_position=serializer.validated_data["last_position"],
            client_event_id=serializer.validated_data.get("client_event_id"),
        )
        return success_response(data=LearningResourceProgressSerializer(prog).data)
