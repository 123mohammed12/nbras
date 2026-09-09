"""
Curriculum Admin configuration with Autocomplete and Search.
"""

from django.contrib import admin
from apps.curriculum.models import (
    AcademicYear,
    DashboardBanner,
    Grade,
    Lesson,
    Section,
    StudyEnrollment,
    Subject,
    Term,
    Topic,
    Unit,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ["code", "name_ar", "starts_at", "ends_at", "status"]
    list_filter = ["status"]
    search_fields = ["code", "name_ar"]


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ["id", "name_ar", "code", "sort_order", "is_active"]
    search_fields = ["id", "name_ar", "code"]
    ordering = ["sort_order", "id"]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ["id", "grade", "name_ar", "code", "sort_order", "is_active"]
    list_filter = ["grade", "is_active"]
    search_fields = ["id", "name_ar"]
    autocomplete_fields = ["grade"]
    list_select_related = ["grade"]
    ordering = ["sort_order", "id"]


@admin.register(StudyEnrollment)
class StudyEnrollmentAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "academic_year", "grade", "section", "status", "is_active", "started_at"]
    list_filter = ["status", "is_active", "grade", "section"]
    search_fields = ["user__phone", "user__public_code"]
    autocomplete_fields = ["academic_year", "grade", "section"]
    list_select_related = ["user", "grade", "section"]
    ordering = ["-created_at"]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ["id", "name_ar", "grade", "section", "status", "sort_order"]
    list_filter = ["grade", "section", "status"]
    search_fields = ["id", "name_ar"]
    autocomplete_fields = ["grade", "section"]
    list_select_related = ["grade", "section"]
    ordering = ["sort_order", "id"]


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["id", "name_ar", "grade", "section", "sort_order", "is_active"]
    list_filter = ["grade", "section", "is_active"]
    search_fields = ["id", "name_ar"]
    autocomplete_fields = ["grade", "section"]
    list_select_related = ["grade", "section"]
    ordering = ["sort_order", "id"]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "subject", "term", "status", "sort_order"]
    list_filter = ["subject__grade", "subject", "status"]
    search_fields = ["id", "title"]
    autocomplete_fields = ["subject", "term"]
    list_select_related = ["subject", "term"]
    ordering = ["sort_order", "id"]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "unit", "estimated_minutes", "status", "sort_order"]
    list_filter = ["unit__subject", "status"]
    search_fields = ["id", "title"]
    autocomplete_fields = ["unit"]
    list_select_related = ["unit"]
    ordering = ["sort_order", "id"]


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "lesson", "code", "status", "sort_order"]
    list_filter = ["status"]
    search_fields = ["id", "title", "code"]
    autocomplete_fields = ["lesson"]
    list_select_related = ["lesson"]
    ordering = ["sort_order", "id"]


@admin.register(DashboardBanner)
class DashboardBannerAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "item_type",
        "badge_text",
        "cta_type",
        "target_id",
        "sort_order",
        "is_active",
        "starts_at",
        "ends_at",
    ]
    list_filter = [
        "item_type",
        "cta_type",
        "is_active",
        "grade",
        "section",
    ]
    search_fields = ["title", "subtitle", "badge_text", "target_id"]
    autocomplete_fields = ["academic_year", "grade", "section"]
    list_select_related = ["academic_year", "grade", "section"]
    ordering = ["sort_order", "-created_at"]

