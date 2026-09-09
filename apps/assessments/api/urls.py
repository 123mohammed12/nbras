from django.urls import path
from apps.assessments.api.views import AssessmentListAPIView, AssessmentDetailAPIView

app_name = "assessments"

urlpatterns = [
    path("assessments/", AssessmentListAPIView.as_view(), name="assessment-list"),
    path("assessments/<uuid:pk>/", AssessmentDetailAPIView.as_view(), name="assessment-detail"),
]
