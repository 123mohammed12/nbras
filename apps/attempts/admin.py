from django.contrib import admin
from apps.attempts.models import (
    AssessmentAttempt, AttemptQuestion, AttemptAnswer, AttemptAnalysis,
    QuestionPerformanceEvidence, QuestionPerformanceEvent,
)


@admin.register(AssessmentAttempt)
class AssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "assessment", "attempt_type", "status", "score", "maximum_score", "percentage"]
    list_filter = ["attempt_type", "status"]
    search_fields = ["user__phone", "user__public_code"]


@admin.register(AttemptQuestion)
class AttemptQuestionAdmin(admin.ModelAdmin):
    list_display = ["id", "attempt", "sort_order", "points"]


@admin.register(AttemptAnswer)
class AttemptAnswerAdmin(admin.ModelAdmin):
    list_display = ["id", "attempt", "attempt_question", "is_correct", "awarded_points"]
    list_filter = ["is_correct"]


@admin.register(AttemptAnalysis)
class AttemptAnalysisAdmin(admin.ModelAdmin):
    list_display = ["attempt", "version", "generated_at"]


@admin.register(QuestionPerformanceEvidence)
class QuestionPerformanceEvidenceAdmin(admin.ModelAdmin):
    list_display = [
        "identity_key", "user", "source_type", "wrong_count",
        "correct_after_wrong_count", "last_outcome", "last_seen_at",
    ]
    list_filter = ["source_type", "difficulty", "question_type", "last_outcome"]
    search_fields = ["identity_key", "user__phone"]


@admin.register(QuestionPerformanceEvent)
class QuestionPerformanceEventAdmin(admin.ModelAdmin):
    list_display = ["attempt_question", "outcome", "awarded_points", "maximum_points", "occurred_at"]
    list_filter = ["outcome"]
