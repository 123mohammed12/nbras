from datetime import timedelta
from threading import Lock

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PushDelivery, PushDevice
from .services import push_allowed

_init_lock = Lock()


def firebase_app():
    import firebase_admin
    from firebase_admin import credentials
    with _init_lock:
        try:
            return firebase_admin.get_app("notifications")
        except ValueError:
            path = settings.FIREBASE_SERVICE_ACCOUNT_PATH
            if not path:
                raise RuntimeError("FIREBASE_NOT_CONFIGURED") from None
            return firebase_admin.initialize_app(credentials.Certificate(path), name="notifications", options={"httpTimeout": 15})


def send_batch(deliveries):
    from firebase_admin import messaging
    messages = []
    for delivery in deliveries:
        n = delivery.recipient.notification
        channel = {"CONTENT": "learning", "LEARNING": "learning", "ASSESSMENT": "assessments", "ACCOUNT": "account", "SUBSCRIPTION": "account"}.get(n.category, "announcements")
        # Generic lock-screen text: private content is fetched only via owned Inbox.
        messages.append(messaging.Message(
            token=delivery.push_device.token,
            data={"recipient_id": str(delivery.recipient_id), "owner_id": str(delivery.recipient.user_id), "channel": channel},
            android=messaging.AndroidConfig(priority="normal" if n.priority == "LOW" else "high", ttl=timedelta(seconds=0)),
        ))
    return messaging.send_each(messages, app=firebase_app()).responses


def dispatch_push(batch_size=100):
    ids = list(PushDelivery.objects.filter(status="PENDING", next_attempt_at__lte=timezone.now()).exclude(recipient__notification__status__in=["SCHEDULED", "PUBLISHING"]).order_by("pk").values_list("pk", flat=True)[:min(batch_size, 100)])
    sent = 0
    # Each bounded transaction locks bindings before outbox rows, matching logout.
    with transaction.atomic():
        binding_ids = list(PushDelivery.objects.filter(pk__in=ids).values_list("push_device_id", flat=True))
        bindings = {b.pk: b for b in PushDevice.objects.select_for_update(skip_locked=True, of=("self",)).filter(pk__in=binding_ids).order_by("pk").select_related("device", "device__user")}
        rows = list(PushDelivery.objects.select_for_update(skip_locked=True, of=("self",)).filter(pk__in=ids, push_device_id__in=bindings, status="PENDING").select_related("recipient__notification", "recipient__user"))
        eligible = []
        now = timezone.now()
        for row in rows:
            binding = bindings[row.push_device_id]
            row.push_device = binding
            n = row.recipient.notification
            if n.status in ("SCHEDULED", "PUBLISHING"):
                continue
            allowed = (n.status == "PUBLISHED" and (not n.expires_at or n.expires_at > now) and n.push_enabled and binding.active and binding.device.is_active and binding.device.user.is_active and binding.device.user_id == row.recipient.user_id and binding.device.sessions.filter(revoked_at__isnull=True, expires_at__gt=now).exists() and push_allowed(row.recipient.user, n.category))
            if not allowed:
                row.status = "SKIPPED"
                row.error_code = "DELIVERY_NOT_ALLOWED"
                row.save(update_fields=["status", "error_code"])
            else:
                eligible.append(row)
        if not eligible:
            return 0
        try:
            responses = send_batch(eligible)
        except Exception:
            # Never log SDK exceptions: they can embed credentials/tokens/payloads.
            responses = [None] * len(eligible)
        for row, response in zip(eligible, responses):
            row.attempt_count += 1
            if response is not None and response.success:
                row.status = "SENT"
                row.sent_at = timezone.now()
                row.error_code = ""
                sent += 1
            else:
                name = type(response.exception).__name__ if response is not None else "ProviderUnavailable"
                invalid = name in ("UnregisteredError", "SenderIdMismatchError")
                permanent = invalid or name == "InvalidArgumentError"
                row.error_code = name if name in ("UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError", "QuotaExceededError", "UnavailableError", "InternalError") else "PROVIDER_UNAVAILABLE"
                if invalid:
                    PushDevice.objects.filter(pk=row.push_device_id).update(active=False)
                if permanent or row.attempt_count >= 5:
                    row.status = "FAILED"
                    row.failed_at = timezone.now()
                else:
                    row.next_attempt_at = timezone.now() + timedelta(minutes=2 ** row.attempt_count)
            row.save()
    return sent
