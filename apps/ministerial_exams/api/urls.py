from django.urls import path
from apps.ministerial_exams.api.views import MinisterialExamListAPIView, MinisterialExamDetailAPIView

app_name = "ministerial_exams"

urlpatterns = [
    path("ministerial-exams/", MinisterialExamListAPIView.as_view(), name="exam-list"),
    path("ministerial-exams/<uuid:pk>/", MinisterialExamDetailAPIView.as_view(), name="exam-detail"),
]
