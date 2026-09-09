from django.contrib import admin
from apps.analytics.models import (
    AnalyticsEvent,
    DailyLearningSummary,
    QuestionQualityAggregate,
    StudentPerformanceInsight,
)


class QualityFlagFilter(admin.SimpleListFilter):
    title = "quality flag"
    parameter_name = "quality_flag"

    def lookups(self, request, model_admin):
        return [
            ("VERY_HIGH_CORRECT_RATE", "Very high correct rate"),
            ("VERY_LOW_CORRECT_RATE", "Very low correct rate"),
            ("HIGH_SKIP_RATE", "High skip rate"),
            ("INEFFECTIVE_DISTRACTOR", "Ineffective distractor"),
            ("POTENTIAL_ANSWER_KEY_ISSUE", "Potential answer-key issue"),
        ]

    def queryset(self, request, queryset):
        return queryset.filter(quality_flags__contains=[self.value()]) if self.value() else queryset


@admin.register(StudentPerformanceInsight)
class StudentPerformanceInsightAdmin(admin.ModelAdmin):
    list_display = ["user", "insight_type", "subject", "unit", "lesson", "score", "evidence_count", "calculated_at"]
    list_filter = ["insight_type"]
    readonly_fields = [
        "user", "study_enrollment", "subject", "unit", "lesson", "insight_type",
        "score", "evidence_count", "message", "calculation_version", "calculated_at", "expires_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(AnalyticsEvent)
class AnalyticsEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "event_type", "user", "source_type", "occurred_at"]
    list_filter = ["event_type", "source_type"]
    readonly_fields = [
        "event_id", "event_type", "schema_version", "user", "study_enrollment",
        "source_type", "source_id", "attempt", "subject", "unit", "lesson",
        "occurred_at", "payload", "created_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(DailyLearningSummary)
class DailyLearningSummaryAdmin(admin.ModelAdmin):
    list_display = ["user", "date", "subject", "learning_seconds", "resources_completed", "attempts_submitted", "updated_at"]
    list_filter = ["date"]
    readonly_fields = [
        "user", "study_enrollment", "date", "subject", "learning_seconds",
        "resources_started", "resources_completed", "attempts_submitted",
        "questions_answered", "correct_answers", "points_earned", "points_possible", "updated_at"
    ]

    def has_add_permission(self, request):
        return False


@admin.register(QuestionQualityAggregate)
class QuestionQualityAggregateAdmin(admin.ModelAdmin):
    list_display = [
        "identity_key",
        "question_version",
        "source_type",
        "subject",
        "sample_size",
        "sample_state",
        "display_correct_rate",
        "display_skip_rate",
        "display_average_score",
        "quality_flags",
    ]
    list_filter = [
        "subject",
        "unit",
        "lesson",
        "source_type",
        "difficulty",
        "question_type",
        "sample_state",
        QualityFlagFilter,
    ]
    search_fields = ["identity_key", "question_version__id"]
    readonly_fields = [
        "identity_key",
        "question_version",
        "ministerial_exam_item",
        "subject",
        "unit",
        "lesson",
        "source_type",
        "difficulty",
        "question_type",
        "presented_count",
        "answered_count",
        "correct_count",
        "incorrect_count",
        "partial_count",
        "unanswered_count",
        "pending_count",
        "earned_points",
        "maximum_gradable_points",
        "response_time_total_seconds",
        "response_time_sample_count",
        "option_distribution",
        "sample_size",
        "sample_state",
        "quality_flags",
        "first_finalized_at",
        "last_finalized_at",
        "updated_at",
    ]
    list_select_related = [
        "question_version",
        "subject",
        "unit",
        "lesson",
        "ministerial_exam_item",
    ]
    ordering = ["-last_finalized_at", "identity_key"]

    @admin.display(description="Correct rate")
    def display_correct_rate(self, obj):
        return "—" if obj.correct_rate is None else f"{obj.correct_rate * 100:.1f}%"

    @admin.display(description="Skip rate")
    def display_skip_rate(self, obj):
        return "—" if obj.skip_rate is None else f"{obj.skip_rate * 100:.1f}%"

    @admin.display(description="Average score")
    def display_average_score(self, obj):
        value = obj.average_points_ratio
        return "—" if value is None else f"{value * 100:.1f}%"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
