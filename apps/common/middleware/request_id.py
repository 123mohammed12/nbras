"""
Request ID Middleware.

Assigns a unique X-Request-ID to every incoming request for
tracing through logs. If the client sends a valid one, it is reused.
Uses contextvars to support multi-threading, ASGI, and async execution safely.
"""

import re
import uuid
import logging
from contextvars import ContextVar

logger = logging.getLogger("apps.common.middleware")

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Valid Request-ID pattern: alphanumeric, hyphen, underscore, 1 to 64 chars.
_REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def get_request_id() -> str | None:
    """Get the current request ID from context storage."""
    return _request_id_ctx.get()


class RequestIDMiddleware:
    """Inject X-Request-ID header into every request/response safely."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming_id = request.META.get("HTTP_X_REQUEST_ID")
        if incoming_id and _REQUEST_ID_REGEX.match(incoming_id):
            request_id = incoming_id
        else:
            request_id = str(uuid.uuid4())

        request.request_id = request_id
        token = _request_id_ctx.set(request_id)

        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            _request_id_ctx.reset(token)
