from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from apps.ministerial_exams.models import MinisterialExam, MinisterialExamSection, MinisterialExamItem
from apps.assessments.models import Assessment, AssessmentType


class MinisterialExamListSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name_ar", read_only=True)
    access = serializers.SerializerMethodField()

    class Meta:
        model = MinisterialExam
        fields = [
            "id",
            "model_code",
            "subject_id",
            "subject_name",
            "exam_year",
            "exam_role",
            "model_number",
            "title",
            "duration_minutes",
            "total_questions",
            "status",
            "free_access_rank",
            "access",
        ]

    def get_access(self, obj):
        decision = getattr(obj, "_access_decision", None)
        return decision.to_dict() if decision else None


class MinisterialExamDetailSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name_ar", read_only=True)
    assessment_id = serializers.SerializerMethodField()
    can_start = serializers.SerializerMethodField()
    supported_modes = serializers.SerializerMethodField()
    shuffle_allowed = serializers.SerializerMethodField()
    source_download_url = serializers.SerializerMethodField()
    access = serializers.SerializerMethodField()

    class Meta:
        model = MinisterialExam
        fields = [
            "id",
            "model_code",
            "subject_id",
            "subject_name",
            "exam_year",
            "exam_role",
            "model_number",
            "title",
            "instructions",
            "duration_minutes",
            "total_points",
            "total_questions",
            "status",
            "published_at",
            "assessment_id",
            "can_start",
            "supported_modes",
            "shuffle_allowed",
            "source_download_url",
            "free_access_rank",
            "access",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_assessment_id(self, obj):
        if obj.assessment_id:
            return str(obj.assessment_id)
        assessment = Assessment.objects.filter(
            subject=obj.subject,
            assessment_type=AssessmentType.MINISTERIAL_EXAM,
            title__contains=obj.title,
        ).first()
        if assessment:
            obj.assessment = assessment
            obj.save(update_fields=["assessment"])
            return str(assessment.id)
        return None


    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_start(self, obj):
        decision = getattr(obj, "_access_decision", None)
        return self.get_assessment_id(obj) is not None and (decision is None or decision.allowed)

    def get_access(self, obj):
        decision = getattr(obj, "_access_decision", None)
        return decision.to_dict() if decision else None

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_supported_modes(self, obj):
        return ["practice", "exam"]

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_shuffle_allowed(self, obj):
        return True

    @extend_schema_field(OpenApiTypes.STR)
    def get_source_download_url(self, obj):
        if obj.source_file_path:
            return f"/api/v1/media/resources/ministerial_exam_source_file/{obj.id}/"
        return None
