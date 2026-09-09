from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.api import error_response, success_response
from apps.downloads.services import (
    PackUnavailable,
    build_subject_download_plan,
    build_unit_manifest,
    current_unit_payload,
)


def _pack_error(exc: PackUnavailable):
    status = 404 if exc.code == "PACK_NOT_FOUND" else 409 if exc.code == "PACK_VERSION_CHANGED" else 403
    return error_response(exc.code, "تعذر توفير حزمة التنزيل المطلوبة.", status=status)


class UnitPackManifestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, unit_id: str):
        try:
            response = success_response(build_unit_manifest(request=request, unit_id=unit_id))
            response["Cache-Control"] = "private, no-store"
            return response
        except PackUnavailable as exc:
            return _pack_error(exc)


class SubjectDownloadPlanView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, subject_id: str):
        try:
            response = success_response(build_subject_download_plan(request=request, subject_id=subject_id))
            response["Cache-Control"] = "private, no-store"
            return response
        except PackUnavailable as exc:
            return _pack_error(exc)


class UnitPayloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, unit_id: str):
        expected = request.query_params.get("checksum", "")
        try:
            body = current_unit_payload(
                request=request, unit_id=unit_id, expected_checksum=expected,
            )
        except PackUnavailable as exc:
            return _pack_error(exc)
        response = HttpResponse(body, content_type="application/json; charset=utf-8")
        response["Content-Length"] = str(len(body))
        response["ETag"] = f'"{expected}"'
        response["Cache-Control"] = "private, no-store"
        return response
