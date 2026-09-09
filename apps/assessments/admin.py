from decimal import Decimal

from django.contrib import admin
from apps.assessments.models import (
    Assessment,
    AssessmentBlueprint,
    AssessmentBlueprintVersion,
    AssessmentItem,
    AssessmentVersion,
    TrainingBatch,
    TrainingBatchItem,
)


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "assessment_type", "subject", "unit", "status"]
    list_filter = ["assessment_type", "status"]
    search_fields = ["title"]


@admin.register(AssessmentVersion)
class AssessmentVersionAdmin(admin.ModelAdmin):
    list_display = ["id", "assessment", "version_number", "duration_minutes", "question_count", "is_current"]
    list_filter = ["is_current", "assessment__assessment_type"]
    search_fields = ["assessment__title"]

    class AssessmentItemInline(admin.TabularInline):
        model = AssessmentItem
        extra = 1
        fields = ["question_version", "ministerial_exam_item", "sort_order", "points", "required"]
        autocomplete_fields = ["question_version", "ministerial_exam_item"]

    inlines = [AssessmentItemInline]

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        version = form.instance
        items = version.items.all()
        version.question_count = items.count()
        version.total_points = sum(
            items.values_list("points", flat=True), Decimal("0.00")
        )
        version.save(update_fields=["question_count", "total_points"])


@admin.register(AssessmentItem)
class AssessmentItemAdmin(admin.ModelAdmin):
    list_display = ["id", "assessment_version", "question_version", "sort_order", "points"]
    list_filter = ["assessment_version__assessment__assessment_type"]
    search_fields = ["assessment_version__assessment__title", "question_version__question_text"]
    autocomplete_fields = ["assessment_version", "question_version", "ministerial_exam_item"]


@admin.register(AssessmentBlueprint)
class AssessmentBlueprintAdmin(admin.ModelAdmin):
    list_display = ["key", "title", "subject", "status", "updated_at"]
    list_filter = ["status", "subject"]
    search_fields = ["key", "title", "subject__name_ar"]


@admin.register(AssessmentBlueprintVersion)
class AssessmentBlueprintVersionAdmin(admin.ModelAdmin):
    list_display = [
        "blueprint", "version_number", "status", "is_current",
        "question_count", "duration_minutes", "total_points", "is_ready",
    ]
    list_filter = ["status", "is_current", "blueprint__subject"]
    readonly_fields = ["readiness_report", "published_at", "created_at"]
    actions = ["validate_and_publish"]

    @admin.display(boolean=True, description="Pool ready")
    def is_ready(self, obj):
        from apps.attempts.services.mock_exams import blueprint_pool_readiness
        return blueprint_pool_readiness(obj)["ready"]

    def readiness_report(self, obj):
        from apps.attempts.services.mock_exams import blueprint_pool_readiness
        return blueprint_pool_readiness(obj)

    @admin.action(description="Validate and publish selected Mock versions")
    def validate_and_publish(self, request, queryset):
        from apps.attempts.services.mock_exams import publish_blueprint_version
        from apps.common.exceptions import ApplicationError
        for version in queryset.select_related("blueprint"):
            try:
                publish_blueprint_version(version)
            except ApplicationError as exc:
                self.message_user(
                    request,
                    f"{version}: {exc.code} {exc.fields or ''}",
                    level="ERROR",
                )
            else:
                self.message_user(request, f"Published {version}.")


class TrainingBatchItemInline(admin.TabularInline):
    model = TrainingBatchItem
    extra = 0
    fields = ["question_version", "sort_order", "source_metadata"]
    raw_id_fields = ["question_version"]
    readonly_fields = ["source_metadata"]


@admin.register(TrainingBatch)
class TrainingBatchAdmin(admin.ModelAdmin):
    list_display = ["scope_key", "scope_type", "batch_index", "free_access_rank", "target_size", "created_at"]
    list_filter = ["scope_type", "subject"]
    search_fields = ["scope_key", "subject__name_ar", "unit__title", "lesson__title"]
    raw_id_fields = ["subject", "unit", "lesson"]
    inlines = [TrainingBatchItemInline]
