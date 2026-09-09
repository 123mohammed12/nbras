from rest_framework import serializers
from apps.progress.models import LessonProgress, UnitProgress, SubjectProgress, LearningSession, LearningResourceProgress
from apps.progress.services.recalculation import (
    compute_subject_accessible_completion,
    compute_unit_accessible_completion,
    compute_lesson_accessible_completion,
)


class ProgressOverviewSerializer(serializers.Serializer):
    enrollment = serializers.DictField(required=False)
    completion = serializers.DictField(required=False)
    performance = serializers.DictField(required=False)
    mastery = serializers.DictField(required=False)
    analytics = serializers.DictField(required=False)
    subjects = serializers.ListField(child=serializers.DictField(), required=False)
    continue_item = serializers.DictField(allow_null=True, required=False)
    recent_activity = serializers.ListField(child=serializers.DictField(), required=False)
    assessment_preview = serializers.ListField(child=serializers.DictField(), required=False)
    updated_at = serializers.DateTimeField(required=False)
    overall_completion_percentage = serializers.FloatField()
    accessible_completion_percentage = serializers.FloatField()
    subjects_count = serializers.IntegerField()
    completed_subjects = serializers.IntegerField()
    total_learning_seconds = serializers.IntegerField()
    active_study_enrollment = serializers.UUIDField(allow_null=True)


class ProgressDetailSerializer(serializers.Serializer):
    scope = serializers.DictField()
    access = serializers.DictField()
    completion = serializers.DictField()
    performance = serializers.DictField()
    mastery = serializers.DictField()
    analytics = serializers.DictField(required=False)
    continue_item = serializers.DictField(allow_null=True)
    children = serializers.ListField(child=serializers.DictField(), required=False)
    learning_activities = serializers.ListField(child=serializers.DictField(), required=False)
    assessments = serializers.ListField(child=serializers.DictField(), required=False)
    recent_activity = serializers.ListField(child=serializers.DictField(), required=False)


class AssessmentHistoryItemSerializer(serializers.Serializer):
    attempt_id = serializers.CharField()
    assessment_id = serializers.CharField(allow_null=True)
    title = serializers.CharField()
    assessment_type = serializers.CharField()
    subject_id = serializers.CharField()
    subject_name = serializers.CharField()
    unit_id = serializers.CharField(allow_null=True)
    lesson_id = serializers.CharField(allow_null=True)
    score = serializers.FloatField()
    maximum_score = serializers.FloatField()
    official_maximum_score = serializers.FloatField()
    percentage = serializers.FloatField()
    attempt_type = serializers.CharField()
    submitted_at = serializers.DateTimeField()


class SubjectProgressSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name_ar", read_only=True)
    accessible_completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = SubjectProgress
        fields = [
            "subject_id",
            "subject_name",
            "status",
            "completion_percentage",
            "accessible_completion_percentage",
            "mastery_percentage",
            "units_completed",
            "units_total",
            "best_score",
            "latest_score",
            "average_score",
            "attempts_count",
            "time_spent_seconds",
            "last_activity_at",
        ]
        
    def get_accessible_completion_percentage(self, obj) -> float:
        ctx = self.context.get("access_context")
        return compute_subject_accessible_completion(
            user=obj.user, enrollment=obj.study_enrollment, subject_id=str(obj.subject_id), context=ctx
        )


class UnitProgressSerializer(serializers.ModelSerializer):
    unit_title = serializers.CharField(source="unit.title", read_only=True)
    accessible_completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = UnitProgress
        fields = [
            "unit_id",
            "unit_title",
            "status",
            "completion_percentage",
            "accessible_completion_percentage",
            "mastery_percentage",
            "lessons_completed",
            "lessons_total",
            "best_score",
            "latest_score",
            "average_score",
            "attempts_count",
            "time_spent_seconds",
            "last_activity_at",
        ]
        
    def get_accessible_completion_percentage(self, obj) -> float:
        ctx = self.context.get("access_context")
        return compute_unit_accessible_completion(
            user=obj.user, enrollment=obj.study_enrollment, unit_id=str(obj.unit_id), context=ctx
        )


class LessonProgressSerializer(serializers.ModelSerializer):
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)
    accessible_completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = LessonProgress
        fields = [
            "lesson_id",
            "lesson_title",
            "status",
            "completion_percentage",
            "accessible_completion_percentage",
            "mastery_percentage",
            "best_score",
            "latest_score",
            "average_score",
            "attempts_count",
            "time_spent_seconds",
            "last_activity_at",
        ]

    def get_accessible_completion_percentage(self, obj) -> float:
        ctx = self.context.get("access_context")
        return compute_lesson_accessible_completion(
            user=obj.user, enrollment=obj.study_enrollment, lesson_id=str(obj.lesson_id), context=ctx
        )




class SessionStartRequestSerializer(serializers.Serializer):
    resource_type = serializers.CharField(max_length=50)
    resource_id = serializers.CharField(max_length=200)
    client_session_id = serializers.CharField(max_length=255)


class ClientEventRequestSerializer(serializers.Serializer):
    client_event_id = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ResourceProgressUpdateRequestSerializer(ClientEventRequestSerializer):
    completion_percentage = serializers.FloatField(min_value=0, max_value=100)
    last_position = serializers.FloatField(min_value=0, max_value=1)


class LearningSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningSession
        fields = ["id", "client_session_id", "status", "started_at", "last_heartbeat_at", "ended_at", "duration_seconds"]


class LearningResourceProgressSerializer(serializers.ModelSerializer):
    last_position = serializers.SerializerMethodField()

    class Meta:
        model = LearningResourceProgress
        fields = [
            "resource_type",
            "resource_id",
            "status",
            "completion_percentage",
            "last_position",
            "time_spent_seconds",
            "started_at",
            "last_activity_at",
            "completed_at",
            "source_version",
        ]

    def get_last_position(self, obj):
        return float((obj.resource_snapshot or {}).get("last_position", 0.0))
