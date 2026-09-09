from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, UserDevice
from apps.curriculum.models import StudyEnrollment
from .actions import validate_action
from .models import Notification, NotificationPreference, NotificationRecipient, PushDelivery, PushDevice


def audience_users(notification):
    qs = User.objects.filter(is_active=True, is_staff=False)
    audience = notification.audience
    if audience == "REGISTERED":
        qs = qs.filter(account_type="registered")
    elif audience == "GUESTS":
        qs = qs.filter(account_type="guest")
    elif audience in ("GRADE", "SECTION", "SUBJECT", "SUBJECT_ACCESS"):
        enrollments = StudyEnrollment.objects.filter(is_active=True, status="active")
        if audience in ("SUBJECT", "SUBJECT_ACCESS"):
            enrollments = enrollments.filter(grade_id=notification.subject.grade_id, section_id=notification.subject.section_id)
        else:
            enrollments = enrollments.filter(grade_id=notification.grade_id)
            if audience == "SECTION":
                enrollments = enrollments.filter(section_id=notification.section_id)
        qs = qs.filter(pk__in=enrollments.values("user_id"))
    elif audience == "USERS":
        qs = qs.filter(pk__in=notification.users.values("pk"))
    elif audience != "EVERYONE":
        return qs.none()
    if notification.audience_cutoff:
        qs = qs.filter(created_at__lte=notification.audience_cutoff)
    return qs.order_by("pk")


@transaction.atomic
def schedule(notification_id):
    n = Notification.objects.select_for_update().get(pk=notification_id)
    if n.status != "DRAFT":
        return n
    n.full_clean()
    objects = validate_action(n.action_type, n.action_payload)
    recipients = audience_users(n)
    if not recipients.exists():
        raise ValidationError("الجمهور فارغ. اختر جمهوراً صريحاً قبل النشر.")
    if "attempt_id" in objects and recipients.exclude(pk=objects["attempt_id"].user_id).exists():
        raise ValidationError("المحاولة خاصة بصاحبها؛ حدد هذا المستخدم فقط.")
    if n.category == "ACCOUNT" and (n.audience != "USERS" or recipients.filter(account_type="guest").exists()):
        raise ValidationError("إشعار الحساب مخصص لمستخدمين مسجلين محددين.")
    n.status = "SCHEDULED"
    n.publish_at = n.publish_at or timezone.now()
    n.save(update_fields=["status", "publish_at", "updated_at"])
    return n


@transaction.atomic
def cancel(notification_id):
    n = Notification.objects.select_for_update().get(pk=notification_id)
    if n.status not in ("DRAFT", "SCHEDULED"):
        raise ValidationError("يمكن إلغاء المسودات والإشعارات المجدولة قبل تجهيزها فقط.")
    n.status = "CANCELLED"
    n.save(update_fields=["status", "updated_at"])


def enqueue_recipients(recipients):
    by_user = {r.user_id: r for r in recipients}
    bindings = PushDevice.objects.filter(active=True, device__is_active=True, device__user_id__in=by_user).select_related("device")
    PushDelivery.objects.bulk_create([
        PushDelivery(recipient=by_user[b.device.user_id], push_device=b) for b in bindings
    ], ignore_conflicts=True, batch_size=500)


@transaction.atomic
def materialize_batch(notification_id, batch_size=500):
    n = Notification.objects.select_for_update().get(pk=notification_id)
    now = timezone.now()
    if n.status not in ("SCHEDULED", "PUBLISHING") or n.publish_at > now:
        return 0
    if n.expires_at and n.expires_at <= now:
        n.status = "EXPIRED"
        n.save(update_fields=["status"])
        return 0
    # Validate again: content may have been unpublished during scheduling.
    try:
        validate_action(n.action_type, n.action_payload)
    except ValidationError:
        n.status = "CANCELLED"
        n.save(update_fields=["status"])
        return 0
    n.audience_cutoff = n.audience_cutoff or now
    qs = audience_users(n)
    if n.audience_cursor:
        qs = qs.filter(pk__gt=n.audience_cursor)
    candidates = list(qs[:batch_size])
    if n.audience == "SUBJECT_ACCESS":
        from apps.entitlements.services.access_service import check_resource_access
        user_ids = [u.pk for u in candidates if check_resource_access(user=u, resource_type="subject", resource_id=n.subject_id).allowed]
    else:
        user_ids = [u.pk for u in candidates]
    NotificationRecipient.objects.bulk_create([
        NotificationRecipient(notification=n, user_id=uid) for uid in user_ids
    ], ignore_conflicts=True, batch_size=batch_size)
    if n.push_enabled:
        enqueue_recipients(list(n.recipients.filter(user_id__in=user_ids)))
    if candidates:
        n.audience_cursor = candidates[-1].pk
    n.status = "PUBLISHING" if len(candidates) == batch_size else "PUBLISHED"
    if n.status == "PUBLISHED":
        n.published_at = now
    n.save()
    return len(user_ids)


@transaction.atomic
def register_device(user, installation_id, token, session_id=None):
    # Serializes registration with account merge and account revocation.
    User.objects.select_for_update().get(pk=user.pk)
    if session_id:
        from apps.accounts.models import UserSession
        if not UserSession.objects.filter(pk=session_id, user=user, device__installation_id=installation_id, revoked_at__isnull=True, expires_at__gt=timezone.now()).exists():
            raise ValidationError("الجلسة غير نشطة.")
    device = UserDevice.objects.select_for_update().get(user=user, installation_id=installation_id, is_active=True)
    # An installation has only one active owner even if accounts keeps device history.
    binding = PushDevice.objects.select_for_update().filter(installation_id=installation_id).first()
    if PushDevice.objects.filter(token=token).exclude(installation_id=installation_id).exists():
        raise ValidationError("رمز الإشعارات مرتبط بتثبيت آخر.")
    if binding:
        if binding.device_id != device.pk or binding.token != token:
            PushDelivery.objects.filter(push_device=binding, status="PENDING").update(status="SKIPPED", error_code="BINDING_CHANGED")
        if binding.token != token:
            binding.token_updated_at = timezone.now()
        binding.device = device
        binding.token = token
        binding.active = True
        binding.last_seen_at = timezone.now()
        binding.save()
    else:
        binding, created = PushDevice.objects.get_or_create(installation_id=installation_id, defaults={"device": device, "token": token})
        if not created:
            # A simultaneous login on the same installation may have won insertion.
            binding = PushDevice.objects.select_for_update().get(pk=binding.pk)
            PushDelivery.objects.filter(push_device=binding, status="PENDING").update(status="SKIPPED", error_code="BINDING_CHANGED")
            binding.device = device
            binding.token = token
            binding.active = True
            binding.token_updated_at = timezone.now()
            binding.last_seen_at = timezone.now()
            binding.save()
    return binding


def disable_devices(device_ids):
    # UPDATE takes row locks; dispatcher holds the same binding lock while sending.
    PushDevice.objects.filter(device_id__in=device_ids).update(active=False)


def push_allowed(user, category):
    key = {"CONTENT": "learning_content", "LEARNING": "learning_content", "ASSESSMENT": "assessment", "SUBSCRIPTION": "subscription", "SYSTEM": "announcements"}.get(category)
    if not key:
        return True
    pref = NotificationPreference.objects.filter(user=user).first()
    return pref is None or getattr(pref, key)


@transaction.atomic
def system_event(*, user, key, title, body, category, action_type="NONE", action_payload=None):
    """Explicit, transactional hook reusable by future backend events."""
    if not user.is_active or (user.is_guest and category in ("ACCOUNT", "SUBSCRIPTION")):
        return None
    validate_action(action_type, action_payload or {})
    n, created = Notification.objects.get_or_create(dedupe_key=key, defaults={
        "title": title, "body": body, "category": category, "source": "SYSTEM",
        "action_type": action_type, "action_payload": action_payload or {},
        "audience": "USERS", "status": "PUBLISHED", "published_at": timezone.now(),
    })
    if created:
        n.users.add(user)
        recipient = NotificationRecipient.objects.create(notification=n, user=user)
        enqueue_recipients([recipient])
    return n


def subscription_event(subscription, kind, threshold=None):
    text = {"activated": ("تم تفعيل الاشتراك", "اشتراكك جاهز للاستخدام."), "expiring": ("اقترب انتهاء الاشتراك", "راجع صفحة الاشتراك لمعرفة مدة الوصول المتبقية."), "expired": ("انتهى الاشتراك", "يمكنك مراجعة خيارات الاشتراك المتاحة.")}
    title, body = text[kind]
    return system_event(user=subscription.user, key=f"subscription_{kind}:{subscription.pk}:{subscription.expires_at.isoformat()}:{threshold or ''}", title=title, body=body, category="SUBSCRIPTION", action_type="OPEN_SUBSCRIPTION")


def generate_subscription_events(batch_size=500):
    from apps.subscriptions.models import Subscription
    now = timezone.now()
    days = settings.NOTIFICATION_EXPIRY_REMINDER_DAYS
    count = 0
    # Idempotency allows bounded progress across repeated cron invocations.
    qs = Subscription.objects.filter(status__in=["active", "expired"], starts_at__lte=now, expires_at__gte=now - timedelta(days=1), expires_at__lte=now + timedelta(days=days), user__is_active=True, user__account_type="registered", study_enrollment__is_active=True).select_related("user")
    for sub in qs.iterator(chunk_size=batch_size):
        if count >= batch_size:
            break
        kind = "expired" if sub.expires_at <= now else "expiring"
        if kind == "expiring" and sub.status != "active":
            continue
        key = f"subscription_{kind}:{sub.pk}:{sub.expires_at.isoformat()}:{days if kind == 'expiring' else ''}"
        if not Notification.objects.filter(dedupe_key=key).exists():
            subscription_event(sub, kind, days if kind == "expiring" else None)
            count += 1
    return count


def merge_notifications(source_guest, target_user):
    # Devices have already been reassigned by the existing first merge handler.
    for binding in PushDevice.objects.select_for_update().filter(device__user=source_guest).select_related("device"):
        target = UserDevice.objects.filter(user=target_user, installation_id=binding.installation_id, is_active=True).first()
        if target:
            binding.device = target
            binding.save(update_fields=["device"])
        else:
            binding.active = False
            binding.save(update_fields=["active"])
    for r in NotificationRecipient.objects.filter(user=source_guest).iterator():
        existing = NotificationRecipient.objects.filter(user=target_user, notification=r.notification).first()
        if existing:
            if existing.read_at is None and r.read_at:
                existing.read_at = r.read_at
                existing.save(update_fields=["read_at"])
            r.delete()
        else:
            r.user = target_user
            r.save(update_fields=["user"])
    pref = NotificationPreference.objects.filter(user=source_guest).first()
    if pref:
        if NotificationPreference.objects.filter(user=target_user).exists():
            pref.delete()
        else:
            pref.user = target_user
            pref.save(update_fields=["user"])
    return {"notifications_merged": True}
