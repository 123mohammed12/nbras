from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count

from .models import Notification, NotificationRecipient, PushDelivery, PushDevice
from .services import audience_users, schedule, cancel


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "source", "category", "audience", "recipient_count", "push_enabled", "publish_at", "expires_at", "created_at"]
    list_filter = ["status", "source", "category", "push_enabled", "created_at", "published_at"]
    search_fields = ["title", "body"]
    raw_id_fields = ["users", "grade", "section", "subject"]
    readonly_fields = ["status", "source", "created_by", "created_at", "published_at", "recipient_count", "audience_estimate", "push_state"]
    fieldsets = [
        ("الرسالة", {"fields": ["title", "body", "category", "priority", "push_enabled"], "description": "نص Push عام وآمن على شاشة القفل. محتوى الرسالة الكامل داخل التطبيق فقط."}),
        ("الجمهور — اختره صراحة", {"fields": ["audience", "grade", "section", "subject", "users", "audience_estimate"]}),
        ("الوجهة الدلالية", {"fields": ["action_type", "action_payload"], "description": "أدخل معرفات JSON فقط وفق عقد docs/notifications.md. لا تدخل مسارات التطبيق."}),
        ("الجدولة", {"fields": ["publish_at", "expires_at"], "description": "احفظ المسودة ثم اختر إجراء النشر من القائمة؛ الوقت الفارغ يعني أقرب دورة إرسال."}),
        ("حالة التسليم", {"fields": ["status", "source", "created_by", "created_at", "published_at", "recipient_count", "push_state"]}),
    ]
    actions = ["publish", "cancel_scheduled"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_recipient_count=Count("recipients"))

    @admin.display(description="المستلمون")
    def recipient_count(self, obj):
        return getattr(obj, "_recipient_count", 0)

    @admin.display(description="تقدير الجمهور بعد الحفظ")
    def audience_estimate(self, obj):
        if not obj or not obj.pk or not obj.audience:
            return "احفظ جمهور المسودة أولاً"
        count = audience_users(obj).count()
        return f"حتى {count} — يُراجع الوصول وقت النشر" if obj.audience == "SUBJECT_ACCESS" else count

    @admin.display(description="Push")
    def push_state(self, obj):
        if not obj or not obj.pk:
            return "—"
        return ", ".join(f"{r['status']}: {r['count']}" for r in PushDelivery.objects.filter(recipient__notification=obj).values("status").annotate(count=Count("pk"))) or "لا إرسال"

    def get_readonly_fields(self, request, obj=None):
        if obj and (obj.status != "DRAFT" or obj.source == "SYSTEM"):
            return list(set(self.readonly_fields + [f.name for f in Notification._meta.fields] + ["users"]))
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="نشر / جدولة المسودات المختارة")
    def publish(self, request, queryset):
        for pk in queryset.values_list("pk", flat=True):
            try:
                schedule(pk)
            except ValidationError as exc:
                self.message_user(request, "؛ ".join(exc.messages), messages.ERROR)
        self.message_user(request, "تمت معالجة المسودات. يقوم dispatch_notifications بتجهيز المستلمين والإرسال.")

    @admin.action(description="إلغاء قبل بدء النشر")
    def cancel_scheduled(self, request, queryset):
        for pk in queryset.values_list("pk", flat=True):
            try:
                cancel(pk)
            except ValidationError as exc:
                self.message_user(request, "؛ ".join(exc.messages), messages.ERROR)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PushDelivery)
class DeliveryAdmin(ReadOnlyAdmin):
    list_display = ["id", "recipient_id", "status", "attempt_count", "next_attempt_at", "sent_at", "error_code"]
    list_filter = ["status", "error_code"]
    exclude = ["push_device"]


@admin.register(PushDevice)
class BindingAdmin(ReadOnlyAdmin):
    list_display = ["id", "device", "active", "last_seen_at", "token_updated_at"]
    exclude = ["token"]
    list_select_related = ["device", "device__user"]
