import mimetypes
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.common.api import error_response
from apps.media_access.registry import MediaResourceRegistry
from apps.media_access.services.authorization_service import authorize_media_access
from apps.downloads.services import calculate_file_checksum


def _bounded_file_iterator(path, start, length, chunk_size=1024 * 1024):
    stream = open(path, "rb")
    try:
        stream.seek(start)
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        stream.close()


class ProtectedResourceMediaView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="تحميل أو عرض ملف وسائط محمي",
        description="جلب الملفات المحمية (ملخصات، بطاقات، مرفقات) عبر معرف المورد المسموح به بعد التحقق من الصلاحيات والاشتراكات.",
        parameters=[
            OpenApiParameter(name="resource_type", type=str, location=OpenApiParameter.PATH, description="نوع المورد المسجل (مثل summary_file, flashcard_front_image)"),
            OpenApiParameter(name="resource_id", type=str, location=OpenApiParameter.PATH, description="معرف الكائن UUID"),
        ],
        responses={
            200: OpenApiResponse(description="إرجاع الملف المحمي"),
            403: OpenApiResponse(description="لا تملك صلاحية الوصول لهذا الملف"),
            404: OpenApiResponse(description="الملف غير موجود أو المورد غير صالح"),
        },
    )
    def get(self, request, resource_type: str, resource_id):
        # 1. Check if resource_type is in closed registry
        definition = MediaResourceRegistry.get(resource_type)
        if not definition:
            return error_response("INVALID_RESOURCE_TYPE", "نوع المورد غير مجاز.", status=404)

        # 2. Get resource object from DB
        model_cls = definition.get_model()
        resource_obj = model_cls.objects.filter(id=resource_id).first()
        if not resource_obj:
            return error_response("RESOURCE_NOT_FOUND", "المورد غير موجود.", status=404)

        # 3. Perform Authorization & Entitlement Checks
        is_authorized, reason = authorize_media_access(
            user=request.user,
            resource=resource_obj,
            definition_model_name=definition.model_name,
        )
        if not is_authorized:
            if reason in ("enrollment_required", "grade_mismatch", "section_mismatch"):
                return error_response("STUDY_SCOPE_DENIED", "لا تنتمي لهذا الصف أو القسم الدراسي.", status=403)
            elif reason in ("subscription_required", "subscription_expired"):
                return error_response("ENTITLEMENT_REQUIRED", "يلزم وجود اشتراك نشط للمادة لتنزيل هذا الملف.", status=403)
            return error_response("ACCESS_DENIED", "غير مصرح لك بالوصول لهذا المحتوى.", status=403)

        # 4. Get FileField value
        file_field = getattr(resource_obj, definition.file_field_name, None)
        if not file_field or not file_field.name:
            return error_response("FILE_NOT_FOUND", "لا يوجد ملف مرفق لهذا المورد.", status=404)

        # 5. Defense in Depth: Path Traversal Check
        file_name = file_field.name
        if ".." in file_name or "\x00" in file_name:
            return error_response("SECURITY_VIOLATION", "مسار الملف غير آمن.", status=404)

        media_root = Path(settings.MEDIA_ROOT).resolve()
        full_path = (media_root / file_name).resolve()

        # Strict check that full_path stays inside media_root
        try:
            if not full_path.is_relative_to(media_root):
                return error_response("PATH_TRAVERSAL_DETECTED", "مسار الملف خارج النطاق المسموح.", status=404)
        except AttributeError:
            if not str(full_path).startswith(str(media_root)):
                return error_response("PATH_TRAVERSAL_DETECTED", "مسار الملف خارج النطاق المسموح.", status=404)

        if not full_path.exists() or not full_path.is_file():
            return error_response("FILE_MISSING", "الملف غير موجود على القرص.", status=404)


        # 6. Build Headers. A strong ETag also gives the unit-pack client a
        # stable integrity identity for resumable transfers.
        content_type, _ = mimetypes.guess_type(str(full_path))
        if not content_type:
            content_type = getattr(resource_obj, "mime_type", None) or "application/octet-stream"

        file_size = full_path.stat().st_size
        filename = Path(full_path).name
        checksum_info = calculate_file_checksum(file_field)
        checksum = checksum_info[1] if checksum_info else None
        etag = f'"{checksum}"' if checksum else None

        if etag and request.headers.get("If-None-Match") == etag:
            response = HttpResponse(status=304)
            response["ETag"] = etag
            response["Cache-Control"] = "private, no-store"
            return response

        # Production Nginx Acceleration
        use_nginx = getattr(settings, "PRIVATE_MEDIA_USE_X_ACCEL", False) or getattr(settings, "USE_NGINX_ACCEL_REDIRECT", False)
        if use_nginx:
            prefix = getattr(settings, "PRIVATE_MEDIA_X_ACCEL_PREFIX", "/protected_media/")
            response = HttpResponse()
            response["X-Accel-Redirect"] = f"{prefix}{file_name}"
            response["Content-Type"] = content_type
            response["Content-Disposition"] = f"{definition.disposition}; filename=\"{filename}\""
            response["X-Content-Type-Options"] = "nosniff"
            response["Cache-Control"] = "private, no-store"
            response["Accept-Ranges"] = "bytes"
            if etag:
                response["ETag"] = etag
            return response

        range_header = request.headers.get("Range", "")
        if_range = request.headers.get("If-Range")
        use_range = range_header.startswith("bytes=") and (not if_range or if_range == etag)
        if use_range:
            try:
                raw_start, raw_end = range_header[6:].split("-", 1)
                start = int(raw_start) if raw_start else 0
                end = int(raw_end) if raw_end else file_size - 1
                if start < 0 or start >= file_size or end < start:
                    raise ValueError
                end = min(end, file_size - 1)
            except (TypeError, ValueError):
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{file_size}"
                return response
            length = end - start + 1
            response = StreamingHttpResponse(
                _bounded_file_iterator(full_path, start, length),
                status=206,
                content_type=content_type,
            )
            response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response["Content-Length"] = str(length)
        else:
            response = FileResponse(open(full_path, "rb"), content_type=content_type)
            response["Content-Length"] = str(file_size)
        response["Content-Disposition"] = f"{definition.disposition}; filename=\"{filename}\""
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        response["Accept-Ranges"] = "bytes"
        if etag:
            response["ETag"] = etag

        return response
