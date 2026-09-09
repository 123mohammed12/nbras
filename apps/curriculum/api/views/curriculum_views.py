"""
Curriculum API Views.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.common.api import error_response, success_response
from apps.common.pagination import StandardPagination
from apps.curriculum.api.serializers.curriculum_serializers import (
    GradeSerializer,
    LessonSerializer,
    SectionSerializer,
    StudyEnrollmentSerializer,
    SubjectSerializer,
    UnitSerializer,
)
from apps.curriculum.api.serializers.dashboard_serializers import (
    CurriculumDashboardResponseSerializer,
    CurriculumDashboardSerializer,
)
from apps.curriculum.api.serializers.subject_center_serializers import (
    SubjectCenterResponseSerializer,
    SubjectCenterSerializer,
)
from apps.curriculum.api.serializers.unit_center_serializers import (
    UnitCenterResponseSerializer,
    UnitCenterSerializer,
)
from apps.curriculum.api.serializers.lesson_center_serializers import (
    LessonCenterResponseSerializer,
    LessonCenterSerializer,
)
from apps.curriculum.models import Lesson, StudyEnrollment, Subject, Unit
from apps.curriculum.selectors.curriculum_selectors import (
    get_active_grades,
    get_grade_sections,
    get_subject_units,
    get_unit_lessons,
    get_user_subjects,
)
from apps.curriculum.selectors.dashboard_selector import get_curriculum_dashboard
from apps.curriculum.selectors.subject_center_selector import get_subject_center
from apps.curriculum.selectors.unit_center_selector import get_unit_center
from apps.curriculum.selectors.lesson_center_selector import get_lesson_center
from apps.curriculum.services.enrollment_service import (
    change_active_study_enrollment,
    create_study_enrollment,
)


class GradeListAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: GradeSerializer(many=True)},
        summary="قائمة الصفوف الدراسية والمسارات الفعالة",
        tags=["Curriculum"],
    )
    def get(self, request):
        grades = get_active_grades()
        serializer = GradeSerializer(grades, many=True)
        return success_response(data=serializer.data)


class SectionListAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: SectionSerializer(many=True)},
        summary="قائمة أقسام / مسارات صف دراسي محدد",
        tags=["Curriculum"],
    )
    def get(self, request, grade_id):
        sections = get_grade_sections(grade_id)
        serializer = SectionSerializer(sections, many=True)
        return success_response(data=serializer.data)


class StudyEnrollmentAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: StudyEnrollmentSerializer},
        summary="عرض الملف الدراسي الحالي للمستخدم",
        tags=["Curriculum Study Enrollment"],
    )
    def get(self, request):
        enrollment = StudyEnrollment.objects.filter(user=request.user, is_active=True).first()
        if not enrollment:
            return error_response(
                code="ENROLLMENT_NOT_FOUND",
                message="لا يوجد ملف دراسي نشط للمستخدم.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = StudyEnrollmentSerializer(enrollment)
        return success_response(data=serializer.data)

    @extend_schema(
        request=inline_serializer(
            "StudyEnrollmentCreateRequest",
            fields={
                "grade_id": drf_serializers.CharField(required=True),
                "section_id": drf_serializers.CharField(required=False, allow_null=True),
            },
        ),
        responses={201: StudyEnrollmentSerializer},
        summary="إنشاء ملف دراسي نشط للمستخدم",
        tags=["Curriculum Study Enrollment"],
    )
    def post(self, request):
        grade_id = request.data.get("grade_id")
        section_id = request.data.get("section_id")

        if not grade_id:
            return error_response(
                code="GRADE_ID_REQUIRED",
                message="grade_id مطلوب.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollment = create_study_enrollment(
            user=request.user, grade_id=grade_id, section_id=section_id
        )
        serializer = StudyEnrollmentSerializer(enrollment)
        return success_response(data=serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=inline_serializer(
            "StudyEnrollmentChangeRequest",
            fields={
                "grade_id": drf_serializers.CharField(required=True),
                "section_id": drf_serializers.CharField(required=False, allow_null=True),
            },
        ),
        responses={200: StudyEnrollmentSerializer},
        summary="تغيير الصف أو القسم الدراسي الحالي",
        tags=["Curriculum Study Enrollment"],
    )
    def patch(self, request):
        new_grade_id = request.data.get("grade_id")
        new_section_id = request.data.get("section_id")

        if not new_grade_id:
            return error_response(
                code="GRADE_ID_REQUIRED",
                message="grade_id مطلوب.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_enr, _ = change_active_study_enrollment(
            user=request.user, new_grade_id=new_grade_id, new_section_id=new_section_id
        )
        serializer = StudyEnrollmentSerializer(new_enr)
        return success_response(data=serializer.data)


class SubjectListAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: SubjectSerializer(many=True)},
        summary="قائمة المواد الدراسية التابعة لصف وقسم الطالب الحالي",
        tags=["Curriculum"],
    )
    def get(self, request):
        grade_id = None
        section_id = None

        if request.user and request.user.is_authenticated:
            enrollment = StudyEnrollment.objects.filter(user=request.user, is_active=True).first()
            if enrollment:
                grade_id = enrollment.grade_id
                section_id = enrollment.section_id

        if not grade_id:
            # Query param overrides if provided
            grade_id = request.query_params.get("grade_id")
            section_id = request.query_params.get("section_id")

        if not grade_id:
            # User has no enrollment and passed no grade_id -> require study selection
            return success_response(
                data={
                    "subjects": [],
                    "requires_study_selection": True,
                    "message": "يرجى تحديد الصف والقسم الدراسي لعرض المواد.",
                }
            )

        subjects = get_user_subjects(grade_id=grade_id, section_id=section_id)
        serializer = SubjectSerializer(subjects, many=True, context={"request": request})
        return success_response(data=serializer.data)


class CurriculumDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CurriculumDashboardResponseSerializer},
        summary="بيانات الشاشة الرئيسية والمواد للمسار الدراسي الحالي",
        tags=["Curriculum"],
    )
    def get(self, request):
        dashboard = get_curriculum_dashboard(request.user)
        if dashboard is None:
            return error_response(
                code="ENROLLMENT_NOT_FOUND",
                message="لا يوجد ملف دراسي نشط للمستخدم.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CurriculumDashboardSerializer(dashboard)
        return success_response(data=serializer.data)


class SubjectDetailAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: SubjectSerializer},
        summary="تفاصيل المادة الدراسية",
        tags=["Curriculum"],
    )
    def get(self, request, pk):
        subject = Subject.objects.filter(id=pk).first()
        if not subject:
            return error_response(
                code="SUBJECT_NOT_FOUND",
                message="المادة غير موجودة.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = SubjectSerializer(subject, context={"request": request})
        return success_response(data=serializer.data)


class SubjectCenterAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: SubjectCenterResponseSerializer},
        summary="مركز المادة والوحدات والنماذج والملخصات والإحصائيات",
        tags=["Curriculum"],
    )
    def get(self, request, subject_id):
        data, missing = get_subject_center(user=request.user, subject_id=subject_id)
        if missing == "enrollment":
            return error_response(
                code="ENROLLMENT_NOT_FOUND",
                message="لا يوجد ملف دراسي نشط للمستخدم.",
                status=status.HTTP_404_NOT_FOUND,
            )
        if missing == "subject":
            return error_response(
                code="SUBJECT_NOT_FOUND",
                message="المادة غير موجودة في المسار الدراسي الحالي.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = SubjectCenterSerializer(data)
        return success_response(data=serializer.data)


class UnitCenterAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UnitCenterResponseSerializer},
        summary="مركز الوحدة والدروس والمحتوى المرتبط",
        tags=["Curriculum"],
    )
    def get(self, request, subject_id, unit_id):
        data, missing = get_unit_center(
            user=request.user,
            subject_id=subject_id,
            unit_id=unit_id,
        )
        if missing == "enrollment":
            return error_response(
                code="ENROLLMENT_NOT_FOUND",
                message="لا يوجد تسجيل دراسي نشط للمستخدم.",
                status=status.HTTP_404_NOT_FOUND,
            )
        if missing == "subject":
            return error_response(
                code="SUBJECT_NOT_FOUND",
                message="المادة غير موجودة في المسار الدراسي الحالي.",
                status=status.HTTP_404_NOT_FOUND,
            )
        if missing == "unit":
            return error_response(
                code="UNIT_NOT_FOUND",
                message="الوحدة لا تنتمي إلى المادة المطلوبة أو غير منشورة.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = UnitCenterSerializer(data)
        return success_response(data=serializer.data)


class LessonCenterAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: LessonCenterResponseSerializer},
        summary="مركز الدرس والمحتوى والموارد المرتبطة",
        tags=["Curriculum"],
    )
    def get(self, request, subject_id, unit_id, lesson_id):
        data, missing = get_lesson_center(
            user=request.user,
            subject_id=subject_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
        )
        if missing == "enrollment":
            return error_response(
                code="ENROLLMENT_NOT_FOUND",
                message="لا يوجد تسجيل دراسي نشط للمستخدم.",
                status=status.HTTP_404_NOT_FOUND,
            )
        if missing == "subject":
            return error_response(
                code="SUBJECT_NOT_FOUND",
                message="المادة غير موجودة في المسار الدراسي الحالي.",
                status=status.HTTP_404_NOT_FOUND,
            )
        if missing == "unit":
            return error_response(
                code="UNIT_NOT_FOUND",
                message="الوحدة لا تنتمي إلى المادة المطلوبة أو غير منشورة.",
                status=status.HTTP_404_NOT_FOUND,
            )
        if missing == "lesson":
            return error_response(
                code="LESSON_NOT_FOUND",
                message="الدرس لا ينتمي إلى الوحدة المطلوبة أو غير منشور.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = LessonCenterSerializer(data)
        return success_response(data=serializer.data)


class SubjectUnitListAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: UnitSerializer(many=True)},
        summary="قائمة وحدات المادة الدراسية",
        tags=["Curriculum"],
    )
    def get(self, request, subject_id):
        units = get_subject_units(subject_id)
        serializer = UnitSerializer(units, many=True, context={"request": request})
        return success_response(data=serializer.data)


class UnitDetailAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: UnitSerializer},
        summary="تفاصيل الوحدة الدراسية والدروس التابعة",
        tags=["Curriculum"],
    )
    def get(self, request, pk):
        unit = Unit.objects.filter(id=pk).prefetch_related("lessons").first()
        if not unit:
            return error_response(
                code="UNIT_NOT_FOUND",
                message="الوحدة غير موجودة.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = UnitSerializer(unit, context={"request": request})
        return success_response(data=serializer.data)


class UnitLessonListAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: LessonSerializer(many=True)},
        summary="قائمة دروس الوحدة الدراسية",
        tags=["Curriculum"],
    )
    def get(self, request, unit_id):
        lessons = get_unit_lessons(unit_id)
        serializer = LessonSerializer(lessons, many=True, context={"request": request})
        return success_response(data=serializer.data)


class LessonDetailAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: LessonSerializer},
        summary="تفاصيل الدرس الدراسي",
        tags=["Curriculum"],
    )
    def get(self, request, pk):
        lesson = Lesson.objects.filter(id=pk).first()
        if not lesson:
            return error_response(
                code="LESSON_NOT_FOUND",
                message="الدرس غير موجود.",
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = LessonSerializer(lesson, context={"request": request})
        return success_response(data=serializer.data)
