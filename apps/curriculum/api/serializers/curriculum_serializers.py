"""
Curriculum API Serializers.
"""

from rest_framework import serializers
from apps.curriculum.models import Grade, Section, Subject, Unit, Lesson, StudyEnrollment


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ["id", "grade_id", "name_ar", "name_en", "code", "sort_order"]


class GradeSerializer(serializers.ModelSerializer):
    sections = SectionSerializer(many=True, read_only=True)

    class Meta:
        model = Grade
        fields = ["id", "name_ar", "name_en", "code", "sort_order", "sections"]


class StudyEnrollmentSerializer(serializers.ModelSerializer):
    grade_name = serializers.CharField(source="grade.name_ar", read_only=True)
    section_name = serializers.CharField(source="section.name_ar", read_only=True)

    class Meta:
        model = StudyEnrollment
        fields = [
            "id",
            "grade_id",
            "grade_name",
            "section_id",
            "section_name",
            "status",
            "is_active",
            "started_at",
            "ended_at",
        ]
        read_only_fields = fields


class SubjectSerializer(serializers.ModelSerializer):
    access_status = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = [
            "id",
            "grade_id",
            "section_id",
            "name_ar",
            "description",
            "icon_path",
            "cover_image_path",
            "sort_order",
            "status",
            "access_status",
        ]

    def get_access_status(self, obj) -> str:
        """
        Check access status via entitlements service if available.
        Does not return a misleading hardcoded 'unlocked'.
        """
        request = self.context.get("request")
        user = request.user if request and hasattr(request, "user") else None

        try:
            from apps.entitlements.services.access_service import check_resource_access
            if user and user.is_authenticated:
                enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
                if enrollment:
                    res = check_resource_access(
                        user=user,
                        enrollment=enrollment,
                        resource_type="subject",
                        resource_id=obj.id,
                    )
                    return "unlocked" if res.allowed else "locked"
        except Exception:
            pass

        return "requires_access_check"


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ["id", "unit_id", "title", "description", "estimated_minutes", "sort_order", "status"]


class UnitSerializer(serializers.ModelSerializer):
    lessons = LessonSerializer(many=True, read_only=True)

    class Meta:
        model = Unit
        fields = ["id", "subject_id", "term_id", "title", "description", "sort_order", "status", "lessons"]
