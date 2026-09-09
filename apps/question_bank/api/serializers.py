from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from apps.question_bank.models import (
    Question,
    QuestionVersion,
    QuestionOption,
    QuestionAsset,
    QuestionStimulus,
)


class QuestionOptionStudentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = QuestionOption
        fields = ["id", "option_key", "option_text", "sort_order", "download_url"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_download_url(self, obj):
        if obj.option_image_path:
            return f"/api/v1/media/resources/question_option_image/{obj.id}/"
        return None


class QuestionOptionAdminSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = QuestionOption
        fields = ["id", "option_key", "option_text", "sort_order", "is_correct", "download_url"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_download_url(self, obj):
        if obj.option_image_path:
            return f"/api/v1/media/resources/question_option_image/{obj.id}/"
        return None


class QuestionAssetSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = QuestionAsset
        fields = ["id", "asset_type", "asset_role", "alt_text", "caption", "sort_order", "download_url"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_download_url(self, obj):
        if obj.file_path:
            return f"/api/v1/media/resources/question_asset/{obj.id}/"
        return None


class QuestionVersionStudentSerializer(serializers.ModelSerializer):
    options = QuestionOptionStudentSerializer(many=True, read_only=True)
    assets = QuestionAssetSerializer(many=True, read_only=True)

    class Meta:
        model = QuestionVersion
        fields = [
            "id",
            "version_number",
            "question_text",
            "prompt_layout",
            "points",
            "options",
            "assets",
        ]


class QuestionVersionAdminSerializer(serializers.ModelSerializer):
    options = QuestionOptionAdminSerializer(many=True, read_only=True)
    assets = QuestionAssetSerializer(many=True, read_only=True)

    class Meta:
        model = QuestionVersion
        fields = [
            "id",
            "version_number",
            "question_text",
            "prompt_layout",
            "short_explanation",
            "explanation",
            "answer_key",
            "points",
            "options",
            "assets",
        ]


class QuestionAdminSerializer(serializers.ModelSerializer):
    current_version = QuestionVersionAdminSerializer(read_only=True)

    class Meta:
        model = Question
        fields = [
            "id",
            "subject_id",
            "unit_id",
            "lesson_id",
            "topic_id",
            "source_type",
            "question_type",
            "difficulty",
            "status",
            "current_version",
            "created_at",
        ]


class QuestionStimulusSerializer(serializers.ModelSerializer):
    image_download_url = serializers.SerializerMethodField()
    file_download_url = serializers.SerializerMethodField()

    class Meta:
        model = QuestionStimulus
        fields = [
            "id",
            "stimulus_type",
            "title",
            "text_content",
            "layout",
            "image_download_url",
            "file_download_url",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image_download_url(self, obj):
        if obj.image_path:
            return f"/api/v1/media/resources/question_stimulus_image/{obj.id}/"
        return None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_download_url(self, obj):
        if obj.file_path:
            return f"/api/v1/media/resources/question_stimulus_file/{obj.id}/"
        return None
