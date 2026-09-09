from django.urls import path
from apps.question_bank.api.views import QuestionAdminListAPIView, QuestionAdminDetailAPIView

app_name = "question_bank"

urlpatterns = [
    path("admin/question-bank/questions/", QuestionAdminListAPIView.as_view(), name="admin-question-list"),
    path("admin/question-bank/questions/<uuid:pk>/", QuestionAdminDetailAPIView.as_view(), name="admin-question-detail"),
]
