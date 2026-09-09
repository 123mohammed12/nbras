from rest_framework import serializers

from apps.curriculum.api.serializers.curriculum_serializers import (
    StudyEnrollmentSerializer,
)


class DashboardAccessSerializer(serializers.Serializer):
    access = serializers.BooleanField()
    allowed = serializers.BooleanField()
    reason_code = serializers.CharField()
    source = serializers.CharField()
    scope_type = serializers.CharField(allow_null=True)
    scope_id = serializers.CharField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    requires_subscription = serializers.BooleanField()
    upgrade_required = serializers.BooleanField()


class DashboardSubjectProgressSerializer(serializers.Serializer):
    status = serializers.CharField()
    completion_percentage = serializers.FloatField()
    accessible_completion_percentage = serializers.FloatField(allow_null=True)
    last_activity_at = serializers.DateTimeField()


class DashboardSubjectSerializer(serializers.Serializer):
    id = serializers.CharField()
    name_ar = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    icon_path = serializers.CharField(allow_null=True)
    cover_image_path = serializers.CharField(allow_null=True)
    published_units_count = serializers.IntegerField()
    published_lessons_count = serializers.IntegerField()
    has_free_content = serializers.BooleanField()
    access_status = serializers.ChoiceField(choices=("unlocked", "partial", "locked"))
    access = DashboardAccessSerializer(allow_null=True)
    progress = DashboardSubjectProgressSerializer(allow_null=True)


class ContinueLearningSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(
        choices=("subject", "unit", "lesson", "assessment", "lesson_explanation", "summary", "flashcard_deck")
    )
    target_id = serializers.CharField()
    subject_id = serializers.CharField()
    subject_name = serializers.CharField()
    unit_id = serializers.CharField(allow_null=True)
    unit_title = serializers.CharField(allow_null=True)
    lesson_id = serializers.CharField(allow_null=True)
    lesson_title = serializers.CharField(allow_null=True)
    completion_percentage = serializers.FloatField()
    last_activity_at = serializers.DateTimeField()


class DashboardSubscriptionSerializer(serializers.Serializer):
    has_active_access = serializers.BooleanField()
    show_offer = serializers.BooleanField()
    active_plan_name = serializers.CharField(allow_null=True)


class DashboardBannerSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True, default="")
    image_url = serializers.CharField(allow_null=True)
    badge = serializers.CharField(allow_blank=True, allow_null=True)
    cta_label = serializers.CharField(allow_blank=True, allow_null=True)
    cta_type = serializers.CharField()
    target_id = serializers.CharField(allow_blank=True, allow_null=True)
    sort_order = serializers.IntegerField()


class CurriculumDashboardSerializer(serializers.Serializer):
    enrollment = StudyEnrollmentSerializer()
    subjects = DashboardSubjectSerializer(many=True)
    continue_learning = ContinueLearningSerializer(allow_null=True)
    subscription = DashboardSubscriptionSerializer()
    carousel_items = DashboardBannerSerializer(many=True, required=False, default=list)


class CurriculumDashboardResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = CurriculumDashboardSerializer()
