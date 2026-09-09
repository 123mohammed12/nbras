from django.contrib import admin
from apps.progress.models import (
    LessonProgress,
    UnitProgress,
    SubjectProgress,
    LearningResourceProgress,
    LearningSession,
    SmartCardReview,
    AttemptProgressReceipt,
)


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "lesson", "status", "completion_percentage", "mastery_percentage", "best_score", "attempts_count", "updated_at"]
    list_filter = ["status"]
    readonly_fields = [
        "user", "study_enrollment", "lesson", "status", "completion_percentage",
        "mastery_percentage", "best_score", "latest_score", "average_score",
        "attempts_count", "time_spent_seconds", "completed_at",
        "mastered_at", "last_activity_at", "created_at", "updated_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(UnitProgress)
class UnitProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "unit", "status", "completion_percentage", "mastery_percentage", "lessons_completed", "best_score", "updated_at"]
    list_filter = ["status"]
    readonly_fields = [
        "user", "study_enrollment", "unit", "status", "completion_percentage",
        "mastery_percentage", "lessons_completed", "lessons_total", "best_score",
        "latest_score", "average_score", "attempts_count", "time_spent_seconds",
        "completed_at", "last_activity_at", "created_at", "updated_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(SubjectProgress)
class SubjectProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "subject", "status", "completion_percentage", "mastery_percentage", "units_completed", "average_score", "updated_at"]
    list_filter = ["status"]
    readonly_fields = [
        "user", "study_enrollment", "subject", "status", "completion_percentage",
        "mastery_percentage", "units_completed", "units_total", "best_score",
        "latest_score", "average_score", "attempts_count", "time_spent_seconds",
        "completed_at", "last_activity_at", "created_at", "updated_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(LearningResourceProgress)
class LearningResourceProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "resource_type", "resource_id", "status", "completion_percentage", "updated_at"]
    list_filter = ["status", "resource_type"]
    readonly_fields = [
        "user", "study_enrollment", "resource_type", "resource_id", "subject",
        "unit", "lesson", "status", "completion_percentage", "time_spent_seconds",
        "started_at", "completed_at", "last_activity_at", "created_at", "updated_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(LearningSession)
class LearningSessionAdmin(admin.ModelAdmin):
    list_display = ["user", "client_session_id", "resource_type", "status", "duration_seconds", "started_at"]
    list_filter = ["status", "resource_type"]
    readonly_fields = [
        "user", "study_enrollment", "client_session_id", "resource_type", "resource_id",
        "subject", "unit", "lesson", "status", "duration_seconds", "started_at",
        "last_heartbeat_at", "ended_at", "created_at", "updated_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(SmartCardReview)
class SmartCardReviewAdmin(admin.ModelAdmin):
    list_display = ["session", "card", "rating", "reviewed_at"]
    list_filter = ["rating"]
    readonly_fields = [
        "session", "card", "rating", "client_event_id", "reviewed_at", "created_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(AttemptProgressReceipt)
class AttemptProgressReceiptAdmin(admin.ModelAdmin):
    list_display = ["attempt", "processed_at"]
    readonly_fields = ["attempt", "processed_at"]

    def has_add_permission(self, request):
        return False
