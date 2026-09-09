from django.contrib import admin
from apps.entitlements.models import Entitlement, PlanEntitlement, UserEntitlement, FreeAccessPolicy


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "scope_type", "entitlement_type", "grade", "section", "subject", "unit", "assessment", "is_active"]
    list_filter = ["scope_type", "entitlement_type", "is_active"]
    search_fields = ["name", "code"]
    autocomplete_fields = ["grade", "section", "subject", "unit", "assessment"]


@admin.register(PlanEntitlement)
class PlanEntitlementAdmin(admin.ModelAdmin):
    list_display = ["plan", "entitlement"]
    list_select_related = ["plan", "entitlement"]
    autocomplete_fields = ["plan", "entitlement"]


@admin.register(UserEntitlement)
class UserEntitlementAdmin(admin.ModelAdmin):
    list_display = ["user", "entitlement", "source", "starts_at", "expires_at", "is_active"]
    list_filter = ["source", "is_active"]
    search_fields = [
        "user__phone",
        "user__public_code",
        "user__student_profile__full_name",
        "entitlement__code",
        "entitlement__name",
    ]
    autocomplete_fields = ["user", "study_enrollment", "entitlement", "granted_by", "revoked_by"]


@admin.register(FreeAccessPolicy)
class FreeAccessPolicyAdmin(admin.ModelAdmin):
    list_display = ["subject", "academic_year", "grade", "section", "free_unit", "subject_summaries_free", "free_ministerial_count", "free_subject_training_count", "free_subject_custom_generations", "free_mock_generations", "is_active"]
    list_filter = ["academic_year", "is_active", "grade", "section"]
    search_fields = ["subject__name", "free_unit__title"]
    autocomplete_fields = ["academic_year", "grade", "section", "subject", "free_unit"]
