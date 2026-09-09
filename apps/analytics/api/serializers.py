from rest_framework import serializers
from apps.analytics.models import StudentPerformanceInsight


class StudentPerformanceInsightSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name_ar", read_only=True)
    unit_title = serializers.CharField(source="unit.title", read_only=True)
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)

    class Meta:
        model = StudentPerformanceInsight
        fields = [
            "id",
            "subject_id",
            "subject_name",
            "unit_id",
            "unit_title",
            "lesson_id",
            "lesson_title",
            "insight_type",
            "score",
            "evidence_count",
            "message",
            "calculated_at",
        ]


class BasicAnalyticsSerializer(serializers.Serializer):
    total_learning_seconds = serializers.IntegerField()
    resources_completed = serializers.IntegerField()
    attempts_submitted = serializers.IntegerField()
    questions_answered = serializers.IntegerField()
    correct_answers = serializers.IntegerField()
    accuracy_percentage = serializers.FloatField()
    recent_activity = serializers.ListField(child=serializers.DictField())
    subject_summaries = serializers.ListField(child=serializers.DictField())
