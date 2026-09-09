"""
Custom DRF exception handler.

Intercepts all exceptions and formats them into the standardized
error response envelope. Never leaks stack traces or raw DB errors.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.common.exceptions import ApplicationError

logger = logging.getLogger("apps.common.exceptions")


def custom_exception_handler(exc, context):
    """
    Custom exception handler that wraps all errors in:
    {
        "success": false,
        "error": {
            "code": "ERROR_CODE",
            "message": "Human-readable message",
            "fields": {}  // optional, for validation errors
        }
    }
    """

    # Handle our custom ApplicationError
    if isinstance(exc, ApplicationError):
        body = {
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }
        if exc.fields:
            body["error"]["fields"] = exc.fields
        return Response(body, status=exc.status_code)

    # Handle Django ValidationError (from model clean() etc.)
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            fields = exc.message_dict
        else:
            fields = {"non_field_errors": exc.messages}
        return Response(
            {
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "بيانات غير صالحة.",
                    "fields": fields,
                },
            },
            status=400,
        )

    # Let DRF handle its own exceptions first
    response = drf_exception_handler(exc, context)

    if response is not None:
        # Map DRF exceptions to our format
        custom_code, custom_message = _extract_validation_code_and_message(exc)
        code = custom_code or _get_error_code(exc)
        message = custom_message or _get_error_message(exc, response)
        fields = _get_field_errors(response)

        response.data = {
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if fields:
            response.data["error"]["fields"] = fields

        return response

    # Unhandled exceptions — log and return generic error
    logger.exception("Unhandled exception: %s", exc, extra={"context": str(context)})
    return Response(
        {
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "حدث خطأ داخلي. يرجى المحاولة لاحقاً.",
            },
        },
        status=500,
    )


def _extract_validation_code_and_message(exc) -> tuple[str | None, str | None]:
    """Extract specific error code and message from DRF ValidationError if available."""
    if not isinstance(exc, drf_exceptions.ValidationError) or not isinstance(exc.detail, dict):
        return None, None

    for _key, value in exc.detail.items():
        items = value if isinstance(value, list) else [value]
        for item in items:
            code = getattr(item, "code", None)
            if code and str(code) not in ("invalid", "required", "blank", "null"):
                code_str = str(code).upper()
                return code_str, str(item)

    return None, None


def _get_error_code(exc) -> str:
    """Map DRF exception types to error codes."""
    code_map = {
        drf_exceptions.AuthenticationFailed: "AUTHENTICATION_FAILED",
        drf_exceptions.NotAuthenticated: "NOT_AUTHENTICATED",
        drf_exceptions.PermissionDenied: "PERMISSION_DENIED",
        drf_exceptions.NotFound: "NOT_FOUND",
        Http404: "NOT_FOUND",
        PermissionDenied: "PERMISSION_DENIED",
        drf_exceptions.Throttled: "RATE_LIMIT_EXCEEDED",
        drf_exceptions.MethodNotAllowed: "METHOD_NOT_ALLOWED",
        drf_exceptions.ValidationError: "VALIDATION_ERROR",
    }
    return code_map.get(type(exc), "REQUEST_ERROR")


def _get_error_message(exc, response) -> str:
    """Extract a human-readable message from the DRF response."""
    if isinstance(exc, drf_exceptions.Throttled):
        wait = exc.wait
        return f"تم تجاوز الحد المسموح. يرجى الانتظار {int(wait)} ثانية." if wait else "تم تجاوز الحد المسموح."

    if isinstance(response.data, dict):
        detail = response.data.get("detail")
        if detail:
            return str(detail)

    if isinstance(response.data, list):
        return str(response.data[0]) if response.data else "حدث خطأ."

    return "حدث خطأ في الطلب."


def _get_field_errors(response) -> dict | None:
    """Extract field-level validation errors from DRF response, ensuring List<String> values."""
    if not isinstance(response.data, dict):
        return None

    fields = {}
    for key, value in response.data.items():
        if key == "detail":
            continue
        if isinstance(value, list):
            string_list = []
            for v in value:
                if isinstance(v, dict):
                    msg = v.get("message") or v.get("detail") or str(v)
                    string_list.append(str(msg))
                else:
                    string_list.append(str(v))
            fields[key] = string_list
        elif isinstance(value, str):
            fields[key] = [value]
        elif isinstance(value, dict):
            msg = value.get("message") or value.get("detail") or str(value)
            fields[key] = [str(msg)]

    return fields or None
