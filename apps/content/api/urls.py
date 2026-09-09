from django.urls import path
from apps.content.api.views import (
    SummaryListAPIView,
    SummaryDetailAPIView,
    FlashcardDeckListAPIView,
    FlashcardDeckCardsAPIView,
    ContentLinkListAPIView,
    LessonExplanationDetailAPIView,
    SmartCardSessionStartAPIView,
    SmartCardSessionReviewAPIView,
)

app_name = "content"

urlpatterns = [
    path("summaries/", SummaryListAPIView.as_view(), name="summary-list"),
    path("summaries/<uuid:pk>/", SummaryDetailAPIView.as_view(), name="summary-detail"),
    path("flashcard-decks/", FlashcardDeckListAPIView.as_view(), name="flashcard-deck-list"),
    path("flashcard-decks/<uuid:pk>/cards/", FlashcardDeckCardsAPIView.as_view(), name="flashcard-deck-cards"),
    path("flashcard-decks/<uuid:pk>/session/", SmartCardSessionStartAPIView.as_view(), name="smart-card-session-start"),
    path("smart-card-sessions/<uuid:session_id>/reviews/", SmartCardSessionReviewAPIView.as_view(), name="smart-card-session-review"),
    path("links/", ContentLinkListAPIView.as_view(), name="content-link-list"),
    path("lessons/<str:lesson_id>/explanation/", LessonExplanationDetailAPIView.as_view(), name="lesson-explanation"),

]
