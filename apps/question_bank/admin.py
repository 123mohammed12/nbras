import json

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import OuterRef, Subquery
from django.shortcuts import render
from django.urls import path
from django.utils.html import format_html, format_html_join

from apps.analytics.models import QuestionQualityAggregate
from apps.curriculum.models import ContentStatus
from apps.question_bank.health import mock_blueprint_health, pool_health, training_batch_health
from apps.question_bank.models import (
    Question, QuestionAsset, QuestionOption, QuestionPool,
    QuestionStimulus, QuestionStimulusLink, QuestionVersion,
)
from apps.question_bank.services import (
    approve_question_version, clone_question_version, create_question_version, publish_question_version,
    retire_question, send_question_version_to_review,
    validate_question_for_publication,
)


def _error_text(exc):
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)


class CurrentQualityFlagFilter(admin.SimpleListFilter):
    title = "إشارة الجودة"
    parameter_name = "quality_flag"

    def lookups(self, request, model_admin):
        return [(value, value) for value in (
            "VERY_HIGH_CORRECT_RATE", "VERY_LOW_CORRECT_RATE", "HIGH_SKIP_RATE",
            "INEFFECTIVE_DISTRACTOR", "POTENTIAL_ANSWER_KEY_ISSUE",
        )]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        return queryset.filter(
            current_version__quality_aggregates__quality_flags__contains=[self.value()]
        ).distinct()


class AdminInputFilter(admin.SimpleListFilter):
    template = "admin/question_bank/input_filter.html"
    field_name = None

    def lookups(self, request, model_admin):
        return ()

    def has_output(self):
        return True

    def queryset(self, request, queryset):
        return queryset.filter(**{self.field_name: self.value()}) if self.value() else queryset


class UnitIdFilter(AdminInputFilter):
    title = "معرّف الوحدة"
    parameter_name = "unit_id"
    field_name = "unit_id"


class SubjectIdFilter(AdminInputFilter):
    title = "معرّف المادة"
    parameter_name = "subject_id"
    field_name = "subject_id"


class LessonIdFilter(AdminInputFilter):
    title = "معرّف الدرس"
    parameter_name = "lesson_id"
    field_name = "lesson_id"


class CreatorIdFilter(AdminInputFilter):
    title = "معرّف المنشئ"
    parameter_name = "created_by_id"
    field_name = "created_by_id"


class ReviewerIdFilter(AdminInputFilter):
    title = "معرّف المراجع"
    parameter_name = "reviewed_by_id"
    field_name = "reviewed_by_id"


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0
    fields = ["option_key", "option_text", "option_image_path", "sort_order", "is_correct"]

    def has_add_permission(self, request, obj=None):
        return bool(obj and not obj.is_frozen and super().has_add_permission(request, obj))

    def has_change_permission(self, request, obj=None):
        return bool((obj is None or not obj.is_frozen) and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return bool((obj is None or not obj.is_frozen) and super().has_delete_permission(request, obj))


class QuestionAssetInline(admin.TabularInline):
    model = QuestionAsset
    extra = 0
    fields = ["asset_type", "asset_role", "file_path", "alt_text", "caption", "sort_order"]

    def has_add_permission(self, request, obj=None):
        return bool(obj and not obj.is_frozen and super().has_add_permission(request, obj))

    def has_change_permission(self, request, obj=None):
        return bool((obj is None or not obj.is_frozen) and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return bool((obj is None or not obj.is_frozen) and super().has_delete_permission(request, obj))


class QuestionVersionHistoryInline(admin.TabularInline):
    model = QuestionVersion
    extra = 0
    show_change_link = True
    can_delete = False
    fields = ["version_number", "status", "is_current", "created_by", "reviewed_by", "approved_by", "published_by", "published_at"]
    readonly_fields = fields
    ordering = ["-version_number"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    change_list_template = "admin/question_bank/question/change_list.html"
    list_display = [
        "id", "subject", "unit", "lesson", "source_type", "question_type",
        "difficulty", "status", "current_version_number", "current_version_status",
        "quality_sample_state", "quality_flags", "created_at",
    ]
    list_filter = [
        "source_type", "question_type", "difficulty", "status", SubjectIdFilter,
        UnitIdFilter, LessonIdFilter, "current_version__status", CurrentQualityFlagFilter,
        CreatorIdFilter, ReviewerIdFilter,
    ]
    search_fields = ["=id", "current_version__question_text", "subject__name_ar"]
    list_select_related = [
        "subject__grade", "unit__subject", "lesson__unit", "current_version",
        "created_by", "reviewed_by",
    ]
    raw_id_fields = ["subject", "unit", "lesson", "topic", "current_version", "created_by", "reviewed_by", "approved_by", "published_by"]
    readonly_fields = [
        "id", "status", "current_version", "quality_summary", "created_at", "updated_at",
        "reviewed_at", "approved_at", "published_at", "retired_at",
    ]
    inlines = [QuestionVersionHistoryInline]
    list_per_page = 50
    list_max_show_all = 200
    show_full_result_count = False
    actions = ["validate_selected", "create_new_version", "assign_self_as_reviewer", "retire_selected"]

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj and obj.current_version and obj.current_version.is_frozen:
            fields.extend([
                "subject", "unit", "lesson", "topic", "source_type",
                "question_type", "difficulty", "metadata", "created_by",
            ])
        return fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.status = ContentStatus.DRAFT
            obj.created_by = obj.created_by or request.user
        super().save_model(request, obj, form, change)
        if not change and not obj.current_version_id:
            create_question_version(
                question=obj, created_by=request.user, set_as_current=True,
            )

    def get_queryset(self, request):
        quality = QuestionQualityAggregate.objects.filter(
            question_version_id=OuterRef("current_version_id")
        ).order_by("-sample_size")
        return super().get_queryset(request).select_related(
            "subject__grade", "unit__subject", "lesson__unit", "current_version",
            "created_by", "reviewed_by"
        ).annotate(
            _quality_sample_state=Subquery(quality.values("sample_state")[:1]),
            _quality_flags=Subquery(quality.values("quality_flags")[:1]),
        )

    @admin.display(description="النسخة")
    def current_version_number(self, obj):
        return obj.current_version.version_number if obj.current_version else "—"

    @admin.display(description="حالة النسخة")
    def current_version_status(self, obj):
        return obj.current_version.get_status_display() if obj.current_version else "—"

    @admin.display(description="حالة العينة", ordering="_quality_sample_state")
    def quality_sample_state(self, obj):
        return obj._quality_sample_state or "—"

    @admin.display(description="إشارات الجودة")
    def quality_flags(self, obj):
        return ", ".join(obj._quality_flags or []) or "—"

    @admin.display(description="ملخص جودة النسخة الحالية")
    def quality_summary(self, obj):
        if not obj or not obj.current_version_id:
            return "—"
        aggregate = QuestionQualityAggregate.objects.filter(
            question_version_id=obj.current_version_id
        ).order_by("-sample_size").first()
        if aggregate is None:
            return "لا توجد عينة جودة بعد."
        correct = "—" if aggregate.correct_rate is None else f"{aggregate.correct_rate * 100:.1f}%"
        skip = "—" if aggregate.skip_rate is None else f"{aggregate.skip_rate * 100:.1f}%"
        score = "—" if aggregate.average_points_ratio is None else f"{aggregate.average_points_ratio * 100:.1f}%"
        return format_html(
            "العينة: {} ({}) — الصحيح: {} — التخطي: {} — المتوسط: {}<br>التوزيع: {}<br>الإشارات: {}",
            aggregate.sample_size, aggregate.sample_state, correct, skip, score,
            json.dumps(aggregate.option_distribution, ensure_ascii=False),
            ", ".join(aggregate.quality_flags) or "—",
        )

    @admin.action(description="تحقق من النسخ الحالية المحددة")
    def validate_selected(self, request, queryset):
        ok, failed, reasons = 0, 0, []
        for question in queryset.select_related("current_version"):
            if not question.current_version:
                failed += 1
                reasons.append(f"{question.pk}: لا توجد نسخة حالية")
                continue
            report = validate_question_for_publication(question.current_version)
            if report["valid"]:
                ok += 1
            else:
                failed += 1
                reasons.append(f"{question.pk}: {'; '.join(report['errors'])}")
        self.message_user(request, f"صالح: {ok}، فاشل: {failed}. {' | '.join(reasons[:10])}", messages.WARNING if failed else messages.SUCCESS)

    @admin.action(description="إنشاء نسخة جديدة")
    def create_new_version(self, request, queryset):
        ok, failed, reasons = 0, 0, []
        for question in queryset:
            try:
                clone_question_version(question=question, actor=request.user)
                ok += 1
            except (ValidationError, PermissionDenied) as exc:
                failed += 1
                reasons.append(f"{question.pk}: {_error_text(exc)}")
        self.message_user(request, f"أُنشئت: {ok}، فشلت: {failed}. {' | '.join(reasons[:10])}", messages.WARNING if failed else messages.SUCCESS)

    @admin.action(description="تعيين نفسي مراجعاً")
    def assign_self_as_reviewer(self, request, queryset):
        if not request.user.has_perm("question_bank.review_question"):
            raise PermissionDenied
        count = queryset.update(reviewed_by=request.user)
        self.message_user(request, f"تم تعيين المراجع لـ {count} سؤال.", messages.SUCCESS)

    @admin.action(description="تقاعد الأسئلة المحددة")
    def retire_selected(self, request, queryset):
        ok, failed = 0, 0
        for question in queryset:
            try:
                retire_question(question=question, actor=request.user)
                ok += 1
            except (ValidationError, PermissionDenied):
                failed += 1
        self.message_user(request, f"تقاعد: {ok}، فشل: {failed}.", messages.WARNING if failed else messages.SUCCESS)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("question_bank.review_question"):
            actions.pop("assign_self_as_reviewer", None)
        if not request.user.has_perm("question_bank.retire_question"):
            actions.pop("retire_selected", None)
        return actions

    def has_delete_permission(self, request, obj=None):
        return bool(obj and not obj.versions.filter(published_at__isnull=False).exists() and super().has_delete_permission(request, obj))

    def get_urls(self):
        return [path("health/", self.admin_site.admin_view(self.health_view), name="question_bank_health")] + super().get_urls()

    def health_view(self, request):
        subject_id = request.GET.get("subject_id") or None
        context = {
            **self.admin_site.each_context(request),
            "title": "صحة بنك الأسئلة",
            "pool": pool_health(subject_id=subject_id),
            "training": training_batch_health(subject_id=subject_id),
            "mock": mock_blueprint_health(subject_id=subject_id),
            "subject_id": subject_id or "",
            "opts": self.model._meta,
        }
        return render(request, "admin/question_bank/question/health.html", context)


@admin.register(QuestionVersion)
class QuestionVersionAdmin(admin.ModelAdmin):
    list_display = ["id", "question", "version_number", "status", "points", "is_current", "published_at", "created_at"]
    list_filter = ["status", "prompt_layout", "is_current", "question__source_type", "question__subject"]
    search_fields = ["question_text", "=question__id", "=id"]
    raw_id_fields = ["question", "created_by", "reviewed_by", "approved_by", "published_by"]
    inlines = [QuestionOptionInline, QuestionAssetInline]
    list_select_related = ["question", "question__subject", "created_by", "reviewed_by", "approved_by", "published_by"]
    list_per_page = 50
    show_full_result_count = False
    readonly_fields = [
        "id", "question", "version_number", "status", "is_current", "preview",
        "reviewed_by", "reviewed_at", "approved_by", "approved_at",
        "published_by", "published_at", "created_at",
    ]
    actions = ["validate_selected", "send_to_review", "approve_selected", "publish_selected"]

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj and obj.is_frozen:
            fields.extend(["question_text", "prompt_layout", "short_explanation", "explanation", "answer_key", "points"])
        return fields

    def has_delete_permission(self, request, obj=None):
        return bool(obj and not obj.is_frozen and super().has_delete_permission(request, obj))

    @admin.display(description="معاينة إدارية")
    def preview(self, obj):
        if not obj:
            return "—"
        options = format_html_join(
            "", "<li dir='rtl'>{} — {} {}</li>",
            ((item.option_key, item.option_text or "[صورة]", "✓" if item.is_correct else "") for item in obj.options.all()),
        )
        assets = format_html_join(
            "", "<li>{}: {}</li>",
            ((item.get_asset_role_display(), item.file_path.name) for item in obj.assets.all()),
        )
        return format_html(
            "<section dir='rtl'><p>{}</p><ul>{}</ul><ul>{}</ul><p><b>الدرجة:</b> {}</p><p><b>الشرح:</b> {}</p><p><b>الإجابة:</b> {}</p></section>",
            obj.question_text or "[سؤال صوري]", options, assets, obj.points,
            obj.explanation or obj.short_explanation or "—",
            json.dumps(obj.answer_key, ensure_ascii=False),
        )

    def _run_action(self, request, queryset, operation):
        ok, failed, reasons = 0, 0, []
        for version in queryset.select_related("question"):
            try:
                operation(version)
                ok += 1
            except (ValidationError, PermissionDenied) as exc:
                failed += 1
                reasons.append(f"{version.pk}: {_error_text(exc)}")
        self.message_user(request, f"نجح: {ok}، فشل: {failed}. {' | '.join(reasons[:10])}", messages.WARNING if failed else messages.SUCCESS)

    @admin.action(description="تحقق من النسخ المحددة")
    def validate_selected(self, request, queryset):
        def validate(version):
            report = validate_question_for_publication(version)
            if not report["valid"]:
                raise ValidationError(report["errors"])
        self._run_action(request, queryset, validate)

    @admin.action(description="إرسال للمراجعة")
    def send_to_review(self, request, queryset):
        self._run_action(request, queryset, lambda version: send_question_version_to_review(version=version, actor=request.user))

    @admin.action(description="اعتماد النسخ المتحققة")
    def approve_selected(self, request, queryset):
        self._run_action(request, queryset, lambda version: approve_question_version(version=version, actor=request.user))

    @admin.action(description="نشر النسخ المتحققة")
    def publish_selected(self, request, queryset):
        self._run_action(request, queryset, lambda version: publish_question_version(version=version, actor=request.user))

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("question_bank.review_question"):
            actions.pop("approve_selected", None)
        if not request.user.has_perm("question_bank.publish_question"):
            actions.pop("publish_selected", None)
        return actions


@admin.register(QuestionAsset)
class QuestionAssetAdmin(admin.ModelAdmin):
    list_display = ["id", "question_version", "asset_type", "asset_role", "file_path"]
    list_filter = ["asset_type", "asset_role"]
    raw_id_fields = ["question_version"]

    def has_change_permission(self, request, obj=None):
        return bool((obj is None or not obj.question_version.is_frozen) and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return bool(obj and not obj.question_version.is_frozen and super().has_delete_permission(request, obj))


@admin.register(QuestionOption)
class QuestionOptionAdmin(admin.ModelAdmin):
    list_display = ["id", "question_version", "option_key", "option_text", "is_correct", "sort_order"]
    list_filter = ["is_correct", "option_key"]
    search_fields = ["option_text", "question_version__question_text"]
    raw_id_fields = ["question_version"]

    def has_change_permission(self, request, obj=None):
        return bool((obj is None or not obj.question_version.is_frozen) and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return bool(obj and not obj.question_version.is_frozen and super().has_delete_permission(request, obj))


@admin.register(QuestionStimulus)
class QuestionStimulusAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "stimulus_type", "subject", "status"]
    list_filter = ["stimulus_type", "status", "subject"]
    search_fields = ["title", "text_content"]
    raw_id_fields = ["subject", "unit", "lesson"]


@admin.register(QuestionPool)
class QuestionPoolAdmin(admin.ModelAdmin):
    list_display = ["id", "pool_type", "subject", "unit", "lesson", "status", "question_count", "updated_at"]
    list_filter = ["pool_type", "status", "subject"]
    readonly_fields = ["question_count", "generated_at", "updated_at"]
