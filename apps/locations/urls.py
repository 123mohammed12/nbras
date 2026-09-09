"""
Locations URLs under /api/v1/locations/
"""

from django.urls import path
from .views import (
    GovernorateListAPIView,
    DistrictListAPIView,
    IsolationListAPIView,
    SchoolListAPIView,
)

urlpatterns = [
    path("governorates/", GovernorateListAPIView.as_view(), name="locations-governorates"),
    path("districts/", DistrictListAPIView.as_view(), name="locations-districts"),
    path("isolations/", IsolationListAPIView.as_view(), name="locations-isolations"),
    path("schools/", SchoolListAPIView.as_view(), name="locations-schools"),
]
