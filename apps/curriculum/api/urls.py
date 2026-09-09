from django.urls import path
from apps.curriculum.api.views.curriculum_views import (
    GradeListAPIView,
    SectionListAPIView,
    StudyEnrollmentAPIView,
    SubjectListAPIView,
    SubjectDetailAPIView,
    SubjectUnitListAPIView,
    UnitDetailAPIView,
    UnitLessonListAPIView,
    LessonDetailAPIView,
    CurriculumDashboardAPIView,
    SubjectCenterAPIView,
    UnitCenterAPIView,
    LessonCenterAPIView,
)

app_name = "curriculum"

urlpatterns = [
    path("grades/", GradeListAPIView.as_view(), name="grade-list"),
    path("grades/<str:grade_id>/sections/", SectionListAPIView.as_view(), name="section-list"),
    path("enrollment/", StudyEnrollmentAPIView.as_view(), name="enrollment-detail"),
    path("dashboard/", CurriculumDashboardAPIView.as_view(), name="dashboard"),
    path("subjects/", SubjectListAPIView.as_view(), name="subject-list"),
    path("subjects/<str:pk>/", SubjectDetailAPIView.as_view(), name="subject-detail"),
    path("subjects/<str:subject_id>/center/", SubjectCenterAPIView.as_view(), name="subject-center"),
    path(
        "subjects/<str:subject_id>/units/<str:unit_id>/center/",
        UnitCenterAPIView.as_view(),
        name="unit-center",
    ),
    path(
        "subjects/<str:subject_id>/units/<str:unit_id>/lessons/<str:lesson_id>/center/",
        LessonCenterAPIView.as_view(),
        name="lesson-center",
    ),
    path("subjects/<str:subject_id>/units/", SubjectUnitListAPIView.as_view(), name="subject-units"),
    path("units/<str:pk>/", UnitDetailAPIView.as_view(), name="unit-detail"),
    path("units/<str:unit_id>/lessons/", UnitLessonListAPIView.as_view(), name="unit-lessons"),
    path("lessons/<str:pk>/", LessonDetailAPIView.as_view(), name="lesson-detail"),
]
