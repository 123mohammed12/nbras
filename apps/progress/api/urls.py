from django.urls import path
from apps.progress.api.views import (
    ProgressOverviewAPIView,
    SubjectProgressDetailAPIView,
    UnitProgressDetailAPIView,
    LessonProgressDetailAPIView,
    SessionStartAPIView,
    SessionHeartbeatAPIView,
    SessionFinishAPIView,
    ResourceStartAPIView,
    ResourceCompleteAPIView,
    ResourceProgressAPIView,
    AssessmentHistoryAPIView,
)

app_name = "progress"

urlpatterns = [
    path("overview/", ProgressOverviewAPIView.as_view(), name="progress_overview"),
    path("subjects/<str:id>/", SubjectProgressDetailAPIView.as_view(), name="subject_progress_detail"),
    path("units/<str:id>/", UnitProgressDetailAPIView.as_view(), name="unit_progress_detail"),
    path("lessons/<str:id>/", LessonProgressDetailAPIView.as_view(), name="lesson_progress_detail"),
    path("history/", AssessmentHistoryAPIView.as_view(), name="assessment_history"),
    
    path("sessions/start/", SessionStartAPIView.as_view(), name="session_start"),
    path("sessions/<str:pk>/heartbeat/", SessionHeartbeatAPIView.as_view(), name="session_heartbeat"),
    path("sessions/<str:pk>/finish/", SessionFinishAPIView.as_view(), name="session_finish"),
    
    path("resources/<str:resource_type>/<str:resource_id>/start/", ResourceStartAPIView.as_view(), name="resource_start"),
    path("resources/<str:resource_type>/<str:resource_id>/complete/", ResourceCompleteAPIView.as_view(), name="resource_complete"),
    path("resources/<str:resource_type>/<str:resource_id>/progress/", ResourceProgressAPIView.as_view(), name="resource_progress"),
]
