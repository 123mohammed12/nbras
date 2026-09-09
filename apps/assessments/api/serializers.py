from rest_framework import serializers
from apps.assessments.models import Assessment, AssessmentVersion


class AssessmentSerializer(serializers.ModelSerializer):
    current_version_id = serializers.UUIDField(source="versions.first.id", read_only=True)

    class Meta:
        model = Assessment
        fields = [
            "id",
            "title",
            "assessment_type",
            "subject_id",
            "unit_id",
            "lesson_id",
            "description",
            "status",
            "current_version_id",
        ]
