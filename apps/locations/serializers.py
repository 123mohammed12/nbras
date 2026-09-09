"""
Locations Serializers with Hierarchy Validation.
"""

from rest_framework import serializers
from apps.locations.models import Governorate, District, Isolation, School
from apps.locations.validators import validate_school_location


class GovernorateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Governorate
        fields = ["id", "name_ar", "code", "sort_order", "is_active"]


class DistrictSerializer(serializers.ModelSerializer):
    governorate_name = serializers.CharField(source="governorate.name_ar", read_only=True)

    class Meta:
        model = District
        fields = ["id", "governorate", "governorate_name", "name_ar", "code", "sort_order", "is_active"]


class IsolationSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source="district.name_ar", read_only=True)

    class Meta:
        model = Isolation
        fields = ["id", "district", "district_name", "name_ar", "code", "sort_order", "is_active"]


class SchoolSerializer(serializers.ModelSerializer):
    governorate_name = serializers.CharField(source="governorate.name_ar", read_only=True)
    district_name = serializers.CharField(source="district.name_ar", read_only=True)
    isolation_name = serializers.CharField(source="isolation.name_ar", read_only=True, allow_null=True)

    class Meta:
        model = School
        fields = [
            "id",
            "governorate",
            "governorate_name",
            "district",
            "district_name",
            "isolation",
            "isolation_name",
            "name_ar",
            "code",
            "school_type",
            "gender_type",
            "is_active",
        ]

    def validate(self, attrs):
        gov = attrs.get("governorate")
        dist = attrs.get("district")
        iso = attrs.get("isolation")
        if gov and dist:
            try:
                validate_school_location(gov, dist, iso)
            except Exception as e:
                raise serializers.ValidationError(str(e))
        return attrs
