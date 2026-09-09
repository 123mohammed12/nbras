"""
Locations Admin interface with Autocomplete and Search.
"""

from django.contrib import admin
from apps.locations.models import Governorate, District, Isolation, School


@admin.register(Governorate)
class GovernorateAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "code", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name_ar", "code")
    ordering = ("sort_order", "name_ar")


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "governorate", "code", "sort_order", "is_active")
    list_filter = ("governorate", "is_active")
    search_fields = ("name_ar", "code", "governorate__name_ar")
    autocomplete_fields = ("governorate",)
    ordering = ("sort_order", "name_ar")


@admin.register(Isolation)
class IsolationAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "district", "code", "sort_order", "is_active")
    list_filter = ("district__governorate", "district", "is_active")
    search_fields = ("name_ar", "code", "district__name_ar")
    autocomplete_fields = ("district",)
    ordering = ("sort_order", "name_ar")


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "governorate", "district", "school_type", "gender_type", "is_active")
    list_filter = ("governorate", "school_type", "gender_type", "is_active")
    search_fields = ("name_ar", "code", "district__name_ar")
    autocomplete_fields = ("governorate", "district", "isolation")
    list_select_related = ("governorate", "district", "isolation")
    ordering = ("name_ar",)
