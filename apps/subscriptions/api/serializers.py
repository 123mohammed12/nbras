from rest_framework import serializers
from django.utils import timezone

from apps.subscriptions.models import PackageTierType, Subscription, SubscriptionPlan


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    regular_price = serializers.DecimalField(source="price", max_digits=10, decimal_places=2, read_only=True)
    display_price = serializers.SerializerMethodField()
    offer_active = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    benefits = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id", "name", "code", "description", "tier_type", "subject_limit",
            "academic_year", "regular_price", "offer_price", "display_price",
            "offer_starts_at", "offer_ends_at", "offer_active", "currency",
            "benefits", "sort_order",
        ]

    def get_display_price(self, obj):
        return f"{obj.current_display_price():.2f}"

    def get_offer_active(self, obj):
        return obj.current_display_price() != obj.price

    def get_academic_year(self, obj):
        if not obj.academic_year_id:
            return None
        return {
            "code": obj.academic_year.code,
            "name": obj.academic_year.name_ar,
            "starts_at": obj.academic_year.starts_at,
            "ends_at": obj.academic_year.ends_at,
        }

    def get_benefits(self, obj):
        if obj.tier_type == PackageTierType.ALL_SUBJECTS:
            scope = "وصول كامل إلى جميع مواد المسار"
        else:
            scope = f"وصول كامل إلى {obj.subject_limit} من المواد"
        return [scope, "يشمل الفصلين الدراسيين", "اختبارات مخصصة ومحاكاة ضمن مخزون الأسئلة الجديد"]


class SubscriptionSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan = SubscriptionPlanSerializer(read_only=True)
    academic_year = serializers.SerializerMethodField()
    selected_subjects = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id", "plan", "plan_name", "academic_year", "status",
            "starts_at", "expires_at", "source", "is_all_subjects",
            "selected_subjects", "created_at",
        ]

    def get_academic_year(self, obj):
        return ({"code": obj.academic_year.code, "name": obj.academic_year.name_ar} if obj.academic_year_id else None)

    def get_status(self, obj):
        if obj.status == "active" and obj.expires_at <= timezone.now():
            return "expired"
        if obj.status == "active" and obj.starts_at > timezone.now():
            return "scheduled"
        return obj.status

    def get_selected_subjects(self, obj):
        return [{"id": str(item.id), "name": item.name_ar} for item in obj.selected_subjects.all()]


class ActivationCodeRequestSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50, trim_whitespace=True)
    subject_ids = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list)


class RedeemRequestSerializer(ActivationCodeRequestSerializer):
    client_request_id = serializers.CharField(max_length=255, required=False)


class RedeemResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    idempotent_replayed = serializers.BooleanField()
    subscription = SubscriptionSerializer()


class AccessCheckQuerySerializer(serializers.Serializer):
    resource_type = serializers.CharField(default="unit")
    resource_id = serializers.CharField()


class AccessDecisionResponseSerializer(serializers.Serializer):
    access = serializers.BooleanField()
    allowed = serializers.BooleanField()
    reason_code = serializers.CharField()
    source = serializers.CharField()
    scope_type = serializers.CharField(allow_null=True)
    scope_id = serializers.CharField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    requires_subscription = serializers.BooleanField()
    upgrade_required = serializers.BooleanField()
