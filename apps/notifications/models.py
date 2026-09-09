import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    class Category(models.TextChoices):
        SYSTEM = "SYSTEM", "إعلانات المنصة"
        CONTENT = "CONTENT", "المحتوى"
        LEARNING = "LEARNING", "التعلم"
        ASSESSMENT = "ASSESSMENT", "الاختبارات والمراجعة"
        SUBSCRIPTION = "SUBSCRIPTION", "الاشتراك"
        ACCOUNT = "ACCOUNT", "الحساب والأمان"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "مسودة"
        SCHEDULED = "SCHEDULED", "مجدول"
        PUBLISHING = "PUBLISHING", "تجهيز المستلمين"
        PUBLISHED = "PUBLISHED", "منشور"
        CANCELLED = "CANCELLED", "ملغى"
        EXPIRED = "EXPIRED", "منتهي"

    class Audience(models.TextChoices):
        EVERYONE = "EVERYONE", "جميع المستخدمين والزوار النشطين"
        REGISTERED = "REGISTERED", "المستخدمون المسجلون"
        GUESTS = "GUESTS", "الزوار"
        GRADE = "GRADE", "صف دراسي"
        SECTION = "SECTION", "صف ومسار"
        SUBJECT = "SUBJECT", "طلاب المادة"
        SUBJECT_ACCESS = "SUBJECT_ACCESS", "طلاب لديهم وصول كامل للمادة"
        USERS = "USERS", "مستخدمون محددون"

    class Action(models.TextChoices):
        NONE = "NONE", "رسالة فقط"
        OPEN_SUBJECT = "OPEN_SUBJECT", "مادة"
        OPEN_UNIT = "OPEN_UNIT", "وحدة"
        OPEN_LESSON = "OPEN_LESSON", "درس"
        OPEN_RESOURCE = "OPEN_RESOURCE", "ملخص"
        OPEN_SMART_CARDS = "OPEN_SMART_CARDS", "بطاقات ذكية"
        OPEN_ATTEMPT = "OPEN_ATTEMPT", "استئناف محاولة"
        OPEN_RESULT = "OPEN_RESULT", "نتيجة محاولة"
        OPEN_SUBSCRIPTION = "OPEN_SUBSCRIPTION", "الاشتراك"
        OPEN_SETTINGS = "OPEN_SETTINGS", "الإعدادات"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=20, choices=Category.choices)
    source = models.CharField(max_length=10, choices=[("ADMIN", "إدارة"), ("SYSTEM", "نظام")], default="ADMIN")
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=2000)
    priority = models.CharField(max_length=10, choices=[("LOW", "منخفض"), ("NORMAL", "عادي"), ("HIGH", "مرتفع")], default="NORMAL")
    action_type = models.CharField(max_length=30, choices=Action.choices, default=Action.NONE)
    action_payload = models.JSONField(default=dict, blank=True)
    push_enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    audience = models.CharField(max_length=20, choices=Audience.choices, blank=True, default="")
    grade = models.ForeignKey("curriculum.Grade", null=True, blank=True, on_delete=models.PROTECT)
    section = models.ForeignKey("curriculum.Section", null=True, blank=True, on_delete=models.PROTECT)
    subject = models.ForeignKey("curriculum.Subject", null=True, blank=True, on_delete=models.PROTECT)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="targeted_notifications")
    publish_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=200, unique=True, null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="authored_notifications")
    audience_cursor = models.UUIDField(null=True, editable=False)
    audience_cutoff = models.DateTimeField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "publish_at"])]
        verbose_name = "إشعار"
        verbose_name_plural = "الإشعارات"
        permissions = [
            ("publish_notification", "Can publish and schedule notifications"),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        from .actions import validate_action
        validate_action(self.action_type, self.action_payload)
        if not self.title.strip() or not self.body.strip():
            raise ValidationError("العنوان والنص مطلوبان.")
        if self.expires_at and self.expires_at <= (self.publish_at or timezone.now()):
            raise ValidationError({"expires_at": "الانتهاء يجب أن يكون بعد النشر."})
        if self.audience in ("GRADE", "SECTION") and not self.grade_id:
            raise ValidationError({"grade": "حدد الصف."})
        if self.audience == "SECTION" and not self.section_id:
            raise ValidationError({"section": "حدد المسار."})
        if self.audience in ("SUBJECT", "SUBJECT_ACCESS") and not self.subject_id:
            raise ValidationError({"subject": "حدد المادة."})
        if self.section_id and self.grade_id and self.section.grade_id != self.grade_id:
            raise ValidationError("المسار لا ينتمي إلى الصف.")


class NotificationRecipient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="recipients")
    # Guests are existing accounts.User rows; no parallel guest identity.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_inbox")
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["notification", "user"], name="nt_unique_recipient")]
        indexes = [models.Index(fields=["user", "read_at"]), models.Index(fields=["user", "-created_at"])]


class PushDevice(models.Model):
    """FCM binding of an existing accounts device, not a second device identity."""
    device = models.OneToOneField("accounts.UserDevice", on_delete=models.CASCADE, related_name="fcm_binding")
    installation_id = models.CharField(max_length=255, unique=True, editable=False)
    token = models.CharField(max_length=1024, unique=True)
    active = models.BooleanField(default=True, db_index=True)
    token_updated_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)


class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    learning_content = models.BooleanField(default=True)
    assessment = models.BooleanField(default=True)
    subscription = models.BooleanField(default=True)
    announcements = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class PushDelivery(models.Model):
    recipient = models.ForeignKey(NotificationRecipient, on_delete=models.CASCADE, related_name="deliveries")
    push_device = models.ForeignKey(PushDevice, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, default="PENDING", choices=[(x, x) for x in ("PENDING", "SENT", "FAILED", "SKIPPED")])
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True)
    failed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["recipient", "push_device"], name="nt_unique_delivery")]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]
