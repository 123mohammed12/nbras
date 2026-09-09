from django.contrib import admin
from apps.ministerial_exams.models import MinisterialExam, MinisterialExamSection, MinisterialExamItem


class MinisterialExamSectionInline(admin.TabularInline):
    model = MinisterialExamSection
    extra = 0
    fields = ["title", "instructions", "sort_order"]


class MinisterialExamItemInline(admin.TabularInline):
    model = MinisterialExamItem
    extra = 0
    fields = ["question_number", "question_version", "sort_order", "points", "official_options_order"]
    raw_id_fields = ["question_version"]


@admin.register(MinisterialExam)
class MinisterialExamAdmin(admin.ModelAdmin):
    list_display = ["id", "model_code", "title", "subject", "exam_year", "exam_role", "model_number", "free_access_rank", "total_questions", "total_points", "status"]
    list_filter = ["exam_year", "exam_role", "status", "subject"]
    search_fields = ["model_code", "title", "subject__name_ar"]
    list_select_related = ["subject", "term"]
    raw_id_fields = ["subject", "term"]
    inlines = [MinisterialExamSectionInline, MinisterialExamItemInline]


@admin.register(MinisterialExamSection)
class MinisterialExamSectionAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "ministerial_exam", "sort_order"]
    search_fields = ["title", "ministerial_exam__title"]
    raw_id_fields = ["ministerial_exam", "stimulus"]


@admin.register(MinisterialExamItem)
class MinisterialExamItemAdmin(admin.ModelAdmin):
    list_display = ["id", "ministerial_exam", "question_number", "question_version", "points", "sort_order"]
    search_fields = ["ministerial_exam__title", "question_number"]
    list_select_related = ["ministerial_exam", "question_version"]
    raw_id_fields = ["ministerial_exam", "section", "question_version"]
