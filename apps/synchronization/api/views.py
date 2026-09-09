from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.common.api import success_response, error_response
from apps.curriculum.models import StudyEnrollment
from apps.synchronization.services import (
    build_full_manifest,
    build_delta_manifest,
    SyncOperationDispatcher,
)
from apps.synchronization.throttles import (
    SyncManifestMinuteRateThrottle,
    SyncManifestHourRateThrottle,
    SyncOperationsMinuteRateThrottle,
    SyncOperationsHourRateThrottle,
)
from apps.synchronization.api.serializers import (
    SyncBatchRequestSerializer,
    SyncBatchResponseSerializer,
    SyncManifestResponseSerializer,
)


class SyncManifestAPIView(APIView):
    """
    Content Discovery Endpoint. Returns Full or Delta Manifest based on cursor presence.
    Supports authenticated users and guests.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [SyncManifestMinuteRateThrottle, SyncManifestHourRateThrottle]

    @extend_schema(
        summary="Fetch Content Manifest (Full or Delta)",
        description=(
            "Retrieves full curriculum manifest or delta updates since last_sequence in server cursor. "
            "Evaluates access decisions and hides sensitive metadata for locked items."
        ),
        parameters=[
            OpenApiParameter("cursor", str, description="Opaque server-signed cursor for Delta Sync.", required=False),
            OpenApiParameter("page", int, description="Page number for Full Manifest.", required=False),
            OpenApiParameter("page_size", int, description="Items per page for Full Manifest (max 200).", required=False),
        ],
        responses={
            200: SyncManifestResponseSerializer,
            400: OpenApiResponse(description="Invalid or corrupted cursor."),
            401: OpenApiResponse(description="Unauthenticated."),
        },
    )
    def get(self, request):
        cursor = request.query_params.get("cursor")
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 100))

        user = request.user
        enrollment = None
        if user and user.is_authenticated:
            enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()

        try:
            if cursor:
                result = build_delta_manifest(
                    user=user,
                    enrollment=enrollment,
                    cursor_str=cursor,
                )
            else:
                result = build_full_manifest(
                    user=user,
                    enrollment=enrollment,
                    page=page,
                    page_size=page_size,
                )
            return Response({"success": True, "data": result}, status=200)

        except ValueError as ve:
            err_code = str(ve)
            if err_code in ["INVALID_CURSOR", "CURSOR_EXPIRED", "CURSOR_OWNERSHIP_MISMATCH", "CURSOR_ENROLLMENT_MISMATCH"]:
                return error_response(
                    code=err_code,
                    message="رمز المؤشر غير صالح أو منتهي الصلاحية.",
                    status=400,
                )
            return error_response(code="BAD_REQUEST", message=str(ve), status=400)


class SyncOperationsBatchAPIView(APIView):
    """
    Ingests and processes client offline operation batches idempotently with partial success semantics.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [SyncOperationsMinuteRateThrottle, SyncOperationsHourRateThrottle]
    serializer_class = SyncBatchRequestSerializer

    @extend_schema(
        summary="Ingest Operations Batch",
        description=(
            "Processes a batch of operations (max 50) atomically per operation. "
            "Guarantees idempotency via client_batch_id and client_operation_id. "
            "Explicitly rejects offline exam attempt submissions."
        ),
        request=SyncBatchRequestSerializer,
        responses={
            200: SyncBatchResponseSerializer,
            400: OpenApiResponse(description="Validation error or batch size exceeded."),
            409: OpenApiResponse(description="Idempotency conflict (same ID, different payload)."),
            413: OpenApiResponse(description="Payload size exceeds limits."),
        },
    )
    def post(self, request):
        serializer = SyncBatchRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                code="VALIDATION_ERROR",
                message="بيانات الدفعة غير صالحة.",
                fields=serializer.errors,
                status=400,
            )

        body_installation_id = serializer.validated_data.get("installation_id")
        header_installation_id = request.headers.get("X-Installation-Id")

        if body_installation_id and header_installation_id and str(body_installation_id) != str(header_installation_id):
            return error_response(
                code="INSTALLATION_ID_MISMATCH",
                message="تعارض بين معرف الجهاز في Header ومعرف الجهاز في Body.",
                status=400,
            )

        installation_id = body_installation_id or header_installation_id
        if not installation_id:
            return error_response(code="MISSING_INSTALLATION_ID", message="حقل installation_id مطلوب.", status=400)

        client_batch_id = serializer.validated_data.get("client_batch_id")
        operations = serializer.validated_data.get("operations", [])

        enrollment = StudyEnrollment.objects.filter(user=request.user, is_active=True).first()

        try:
            raw_bytes = int(request.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            raw_bytes = 0

        if raw_bytes == 0 and request.data:
            import json
            raw_bytes = len(json.dumps(request.data).encode("utf-8"))

        dispatcher = SyncOperationDispatcher(
            user=request.user,
            installation_id=installation_id,
            enrollment=enrollment,
            raw_request_bytes=raw_bytes,
        )

        response_data, status_code = dispatcher.dispatch_batch(
            client_batch_id=client_batch_id,
            operations=operations,
        )

        return Response(response_data, status=status_code)
