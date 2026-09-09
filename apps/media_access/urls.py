from django.urls import path
from apps.media_access.views import ProtectedResourceMediaView

app_name = "media_access"

urlpatterns = [
    path(
        "media/resources/<str:resource_type>/<uuid:resource_id>/",
        ProtectedResourceMediaView.as_view(),
        name="resource-media",
    ),
]
