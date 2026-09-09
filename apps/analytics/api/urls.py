from django.urls import path
from apps.analytics.api.views import BasicAnalyticsAPIView, StrengthsAnalyticsAPIView, WeaknessesAnalyticsAPIView

app_name = "analytics"

urlpatterns = [
    path("analytics/basic/", BasicAnalyticsAPIView.as_view(), name="analytics-basic"),
    path("analytics/strengths/", StrengthsAnalyticsAPIView.as_view(), name="analytics-strengths"),
    path("analytics/weaknesses/", WeaknessesAnalyticsAPIView.as_view(), name="analytics-weaknesses"),
]
