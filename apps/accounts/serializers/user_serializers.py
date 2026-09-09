"""
User Serializers.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import StudentProfile, User
from apps.locations.models import District, Governorate, Isolation, School


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "public_code",
            "account_type",
            "phone",
            "phone_verified_at",
            "upgraded_at",
            "date_joined",
            "last_login",
        ]
        read_only_fields = fields


class StudentProfileSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source="user.phone", read_only=True)
    governorate_name = serializers.CharField(source="governorate.name_ar", read_only=True, allow_null=True)
    district_name = serializers.CharField(source="district.name_ar", read_only=True, allow_null=True)
    isolation_name = serializers.CharField(source="isolation.name_ar", read_only=True, allow_null=True)
    school_name = serializers.CharField(source="school.name_ar", read_only=True, allow_null=True)
    governorate = serializers.PrimaryKeyRelatedField(queryset=Governorate.objects.filter(is_active=True), required=False, allow_null=True)
    district = serializers.PrimaryKeyRelatedField(queryset=District.objects.filter(is_active=True), required=False, allow_null=True)
    isolation = serializers.PrimaryKeyRelatedField(queryset=Isolation.objects.filter(is_active=True), required=False, allow_null=True)
    school = serializers.PrimaryKeyRelatedField(queryset=School.objects.filter(is_active=True), required=False, allow_null=True)

    class Meta:
        model = StudentProfile
        fields = [
            "id", "full_name", "phone",
            "governorate", "governorate_name", "custom_governorate_name",
            "district", "district_name", "custom_district_name",
            "isolation", "isolation_name", "custom_isolation_name",
            "school", "school_name", "custom_school_name", "updated_at",
        ]
        read_only_fields = ["id", "phone", "updated_at"]

    def validate(self, attrs):
        current = self.instance

        def value(field):
            return attrs[field] if field in attrs else getattr(current, field, None)

        for field in ("custom_governorate_name", "custom_district_name", "custom_isolation_name", "custom_school_name"):
            if field in attrs:
                attrs[field] = attrs[field].strip()

        governorate, district = value("governorate"), value("district")
        isolation, school = value("isolation"), value("school")
        custom_governorate = value("custom_governorate_name") or ""
        custom_district = value("custom_district_name") or ""
        custom_isolation = value("custom_isolation_name") or ""
        custom_school = value("custom_school_name") or ""
        errors = {}
        pairs = (
            ("governorate", governorate, "custom_governorate_name", custom_governorate),
            ("district", district, "custom_district_name", custom_district),
            ("isolation", isolation, "custom_isolation_name", custom_isolation),
            ("school", school, "custom_school_name", custom_school),
        )
        for _, canonical, custom_field, custom in pairs:
            if canonical is not None and custom:
                errors[custom_field] = ["اختر قيمة من القائمة أو أدخل قيمة أخرى، وليس كليهما."]
        if district and (not governorate or district.governorate_id != governorate.id):
            errors["district"] = ["المديرية لا تتبع المحافظة المختارة."]
        if isolation and (not district or isolation.district_id != district.id):
            errors["isolation"] = ["العزلة لا تتبع المديرية المختارة."]
        if school:
            if not governorate or not district:
                errors["school"] = ["اختيار مدرسة معتمدة يتطلب محافظة ومديرية معتمدتين."]
            elif school.governorate_id != governorate.id or school.district_id != district.id:
                errors["school"] = ["المدرسة لا تتبع الموقع المختار."]
            elif isolation and school.isolation_id and school.isolation_id != isolation.id:
                errors["school"] = ["المدرسة لا تتبع العزلة المختارة."]
        if custom_district and not (governorate or custom_governorate):
            errors["custom_district_name"] = ["أدخل المحافظة أولاً."]
        if custom_isolation and not (district or custom_district):
            errors["custom_isolation_name"] = ["أدخل المديرية أولاً."]
        if custom_school and not (district or custom_district):
            errors["custom_school_name"] = ["أدخل المديرية أولاً."]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(getattr(exc, "message_dict", {"non_field_errors": exc.messages}))
        instance.save()
        return instance


class AccountDeactivationSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, allow_blank=False, trim_whitespace=False, max_length=128)
