"""
Idempotency Key support and enforcement.

Prevents duplicate side-effects when clients retry requests.
PostgreSQL is the single source of truth for idempotency records and atomic locks.
"""

import hashlib
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

from apps.common.models import IdempotencyRecord

logger = logging.getLogger("apps.common.idempotency")


def get_idempotency_key(request) -> str | None:
    """Extract and validate idempotency key from request header."""
    max_len = getattr(settings, "IDEMPOTENCY_MAX_KEY_LENGTH", 128)
    key = request.META.get("HTTP_IDEMPOTENCY_KEY") or request.META.get(
        "HTTP_X_IDEMPOTENCY_KEY"
    )
    if not key or not isinstance(key, str):
        return None
    key = key.strip()
    if not key or len(key) > max_len:
        return None
    return key


def build_actor_scope(request) -> str:
    """
    Build a unique actor scope string for the client.
    User actor: user:<user_id>
    Guest actor: guest:<installation_id>
    Anon actor: anon:<ip_hash>
    """
    if getattr(request, "user", None) and request.user.is_authenticated:
        return f"user:{request.user.id}"

    # Check installation_id for guests
    installation_id = (
        request.META.get("HTTP_X_INSTALLATION_ID")
        or request.headers.get("X-Installation-ID")
    )
    if not installation_id and isinstance(getattr(request, "data", None), dict):
        installation_id = request.data.get("installation_id")

    if installation_id and isinstance(installation_id, str) and installation_id.strip():
        return f"guest:{installation_id.strip()}"

    # Fallback to hashed IP
    ip = request.META.get("REMOTE_ADDR") or "127.0.0.1"
    ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]
    return f"anon:{ip_hash}"


def compute_request_hash(request, actor_scope: str) -> str:
    """
    Compute a SHA-256 fingerprint for the request parameters.
    Ignores non-functional headers or auth tokens.
    """
    method = request.method.upper()
    endpoint = request.path
    query_str = request.GET.urlencode()

    payload_str = ""
    data = getattr(request, "data", None)
    if isinstance(data, dict):
        try:
            payload_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            payload_str = str(data)
    elif data is not None:
        payload_str = str(data)

    raw_fingerprint = f"{method}|{endpoint}|{query_str}|{payload_str}|{actor_scope}"
    return hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()


def process_idempotent_request(request, view_func, self_obj, args, kwargs):
    """
    Execute view idempotently backed by PostgreSQL atomic transactions.
    """
    idem_key = get_idempotency_key(request)
    if not idem_key:
        return view_func(self_obj, request, *args, **kwargs) if self_obj else view_func(request, *args, **kwargs)

    actor_scope = build_actor_scope(request)
    request_hash = compute_request_hash(request, actor_scope)
    endpoint = request.path
    now = timezone.now()

    ttl_seconds = getattr(settings, "IDEMPOTENCY_TTL_SECONDS", 86400)
    lock_seconds = getattr(settings, "IDEMPOTENCY_LOCK_SECONDS", 60)
    max_response_bytes = getattr(settings, "IDEMPOTENCY_MAX_RESPONSE_BYTES", 262144)

    record = None
    is_new = False

    # Attempt to fetch or create processing record atomically
    try:
        with transaction.atomic():
            record = (
                IdempotencyRecord.objects.select_for_update()
                .filter(actor_scope=actor_scope, endpoint=endpoint, key=idem_key)
                .first()
            )
            if not record:
                record = IdempotencyRecord.objects.create(
                    user=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
                    actor_scope=actor_scope,
                    key=idem_key,
                    method=request.method.upper(),
                    endpoint=endpoint,
                    request_hash=request_hash,
                    status=IdempotencyRecord.Status.PROCESSING,
                    locked_until=now + timedelta(seconds=lock_seconds),
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
                is_new = True
    except IntegrityError:
        record = IdempotencyRecord.objects.filter(
            actor_scope=actor_scope, endpoint=endpoint, key=idem_key
        ).first()
        is_new = False

    if not is_new and record:
        # Existing record handling
        if record.status == IdempotencyRecord.Status.COMPLETED:
            if record.request_hash == request_hash:
                logger.info("Idempotency replay for key %s (actor: %s)", idem_key[:8], actor_scope)
                resp = Response(record.response_body, status=record.response_status or 200)
                resp["Idempotency-Replayed"] = "true"
                return resp
            else:
                logger.warning("Idempotency payload mismatch for key %s", idem_key)
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "IDEMPOTENCY_PAYLOAD_MISMATCH",
                            "message": "تم إرسال طلب بمفتاح تكرار سابق ولكن بحمولة مختلفة.",
                        },
                    },
                    status=409,
                )

        if record.status == IdempotencyRecord.Status.PROCESSING:
            if record.locked_until and now < record.locked_until:
                logger.info("Idempotency request in progress for key %s", idem_key)
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "IDEMPOTENCY_IN_PROGRESS",
                            "message": "الطلب قيد المعالجة حالياً. يرجى الانتظار.",
                        },
                    },
                    status=409,
                )
            else:
                # Lock expired, recover execution
                with transaction.atomic():
                    IdempotencyRecord.objects.filter(id=record.id).update(
                        status=IdempotencyRecord.Status.PROCESSING,
                        request_hash=request_hash,
                        locked_until=now + timedelta(seconds=lock_seconds),
                        expires_at=now + timedelta(seconds=ttl_seconds),
                    )

    # Execute original view function
    try:
        if self_obj is not None:
            response = view_func(self_obj, request, *args, **kwargs)
        else:
            response = view_func(request, *args, **kwargs)
    except Exception as exc:
        if record:
            IdempotencyRecord.objects.filter(id=record.id).update(
                status=IdempotencyRecord.Status.FAILED,
                locked_until=None,
            )
        raise exc

    # Evaluate response result
    if record:
        if 200 <= response.status_code < 300:
            resp_data = getattr(response, "data", None)
            try:
                # DRF serializer data may still contain UUID/Decimal/datetime
                # values before renderer negotiation. Persist the same JSON-safe
                # primitives that the client receives.
                stored_body = (
                    json.loads(json.dumps(resp_data, cls=DjangoJSONEncoder, ensure_ascii=False))
                    if resp_data is not None
                    else None
                )
                data_bytes = len(json.dumps(stored_body, ensure_ascii=False).encode("utf-8")) if stored_body else 0
            except (TypeError, ValueError):
                data_bytes = 0
                stored_body = None

            if data_bytes > max_response_bytes:
                logger.warning("Response payload exceeds max size (%d > %d) for key %s", data_bytes, max_response_bytes, idem_key)
                stored_body = {
                    "_truncated": True,
                    "_message": "حجم الاستجابة يتجاوز الحد المسموح للتخزين.",
                }
            IdempotencyRecord.objects.filter(id=record.id).update(
                status=IdempotencyRecord.Status.COMPLETED,
                response_status=response.status_code,
                response_body=stored_body,
                locked_until=None,
            )
        else:
            IdempotencyRecord.objects.filter(id=record.id).update(
                status=IdempotencyRecord.Status.FAILED,
                locked_until=None,
            )

    return response


def idempotent_view(view_func):
    """
    Decorator for views supporting Idempotency-Key header.
    Fully compatible with class-based views (methods) and function-based views.
    """
    def wrapper(*args, **kwargs):
        # Determine if class method (self, request, ...) or function view (request, ...)
        if len(args) >= 2 and hasattr(args[1], "META"):
            self_obj = args[0]
            request = args[1]
            func_args = args[2:]
        elif len(args) >= 1 and hasattr(args[0], "META"):
            self_obj = None
            request = args[0]
            func_args = args[1:]
        else:
            # Fallback
            return view_func(*args, **kwargs)

        return process_idempotent_request(request, view_func, self_obj, func_args, kwargs)

    return wrapper
