from django.contrib import admin
from apps.content.models import Summary, FlashcardDeck, Flashcard, ContentLink, LessonExplanation


@admin.register(LessonExplanation)
class LessonExplanationAdmin(admin.ModelAdmin):
    list_display = ["id", "lesson", "title", "content_format", "status", "updated_at"]
    list_filter = ["content_format", "status"]
    search_fields = ["title", "body", "lesson__title"]
    raw_id_fields = ["lesson"]


@admin.register(Summary)
class SummaryAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "summary_type", "subject", "unit", "lesson", "status"]
    list_filter = ["summary_type", "status"]
    search_fields = ["title"]
    raw_id_fields = ["subject", "unit", "lesson"]


@admin.register(FlashcardDeck)
class FlashcardDeckAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "subject", "unit", "lesson", "status"]
    list_filter = ["status"]
    raw_id_fields = ["subject", "unit", "lesson"]


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = ["id", "deck", "difficulty", "sort_order", "is_active"]
    list_filter = ["difficulty", "is_active"]
    raw_id_fields = ["deck"]


@admin.register(ContentLink)
class ContentLinkAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "link_type", "subject", "unit", "lesson", "status"]
    list_filter = ["link_type", "status"]
    raw_id_fields = ["subject", "unit", "lesson"]
