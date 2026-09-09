from rest_framework import serializers
from django.urls import reverse
from apps.content.models import Summary, FlashcardDeck, Flashcard, ContentLink, LessonExplanation


class LessonExplanationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonExplanation
        fields = [
            "id",
            "lesson_id",
            "title",
            "body",
            "content_format",
            "version",
            "published_at",
        ]


class SummarySerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    content_format = serializers.SerializerMethodField()
    subject_name = serializers.CharField(source="subject.name_ar", read_only=True, allow_null=True)
    unit_name = serializers.CharField(source="unit.title", read_only=True, allow_null=True)
    lesson_name = serializers.CharField(source="lesson.title", read_only=True, allow_null=True)

    class Meta:
        model = Summary
        fields = [
            "id",
            "title",
            "description",
            "summary_type",
            "subject_id",
            "subject_name",
            "unit_id",
            "unit_name",
            "lesson_id",
            "lesson_name",
            "body",
            "content_format",
            "file_name",
            "file_size",
            "mime_type",
            "file_checksum",
            "version",
            "sort_order",
            "is_downloadable",
            "download_url",
            "status",
            "created_at",
            "updated_at",
        ]

    def get_description(self, obj) -> str:
        # Summary currently has no dedicated description column.
        return ""

    def get_content_format(self, obj) -> str:
        return "markdown"

    def get_download_url(self, obj) -> str | None:
        if not obj.file_path:
            return None
        request = self.context.get("request")
        url = reverse("media_access:resource-media", kwargs={"resource_type": "summary_file", "resource_id": obj.id})

        return request.build_absolute_uri(url) if request else url


class FlashcardSerializer(serializers.ModelSerializer):
    deck_id = serializers.UUIDField(read_only=True)
    front_image_url = serializers.SerializerMethodField()
    back_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Flashcard
        fields = [
            "id",
            "deck_id",
            "front_text",
            "back_text",
            "front_image_url",
            "back_image_url",
            "explanation",
            "difficulty",
            "sort_order",
        ]

    def get_front_image_url(self, obj) -> str | None:
        if not obj.front_image_path:
            return None
        request = self.context.get("request")
        url = reverse("media_access:resource-media", kwargs={"resource_type": "flashcard_front_image", "resource_id": obj.id})
        return request.build_absolute_uri(url) if request else url

    def get_back_image_url(self, obj) -> str | None:
        if not obj.back_image_path:
            return None
        request = self.context.get("request")
        url = reverse("media_access:resource-media", kwargs={"resource_type": "flashcard_back_image", "resource_id": obj.id})
        return request.build_absolute_uri(url) if request else url


class FlashcardDeckSerializer(serializers.ModelSerializer):
    cards_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = FlashcardDeck
        fields = ["id", "title", "description", "subject_id", "unit_id", "lesson_id", "status", "cards_count"]


class SmartCardSessionStartRequestSerializer(serializers.Serializer):
    client_session_id = serializers.CharField(max_length=255)


class SmartCardReviewRequestSerializer(serializers.Serializer):
    card_id = serializers.UUIDField()
    rating = serializers.ChoiceField(choices=["again", "hard", "good"])
    client_event_id = serializers.CharField(max_length=255)
    reviewed_at = serializers.DateTimeField(required=False)


class SmartCardReviewSerializer(serializers.Serializer):
    card_id = serializers.UUIDField()
    rating = serializers.CharField()
    client_event_id = serializers.CharField()
    reviewed_at = serializers.DateTimeField()


class SmartCardSessionStateSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    client_session_id = serializers.CharField()
    source_type = serializers.CharField()
    source_id = serializers.CharField()
    status = serializers.CharField()
    total_cards = serializers.IntegerField()
    current_position = serializers.IntegerField()
    reviewed_count = serializers.IntegerField()
    remaining_count = serializers.IntegerField()
    rating_counts = serializers.DictField(child=serializers.IntegerField())
    completed_at = serializers.DateTimeField(allow_null=True)


class SmartCardSessionSerializer(SmartCardSessionStateSerializer):
    deck = serializers.DictField()
    cards = serializers.ListField(child=serializers.DictField())
    allowed_review_actions = serializers.ListField(child=serializers.DictField())
    access = serializers.DictField()


class ContentLinkSerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.SerializerMethodField()
    attached_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ContentLink
        fields = [
            "id",
            "title",
            "url",
            "link_type",
            "subject_id",
            "unit_id",
            "lesson_id",
            "description",
            "thumbnail_url",
            "attached_file_url",
            "duration_seconds",
            "status",
            "is_external",
        ]

    def get_thumbnail_url(self, obj) -> str | None:
        if not obj.thumbnail_path:
            return None
        request = self.context.get("request")
        url = reverse("media_access:resource-media", kwargs={"resource_type": "content_link_thumbnail", "resource_id": obj.id})
        return request.build_absolute_uri(url) if request else url

    def get_attached_file_url(self, obj) -> str | None:
        if not obj.attached_file_path:
            return None
        request = self.context.get("request")
        url = reverse("media_access:resource-media", kwargs={"resource_type": "content_link_file", "resource_id": obj.id})
        return request.build_absolute_uri(url) if request else url
