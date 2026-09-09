from django.urls import path
from apps.synchronization.api.views import SyncManifestAPIView, SyncOperationsBatchAPIView

app_name = "synchronization"

urlpatterns = [
    path("sync/manifest/", SyncManifestAPIView.as_view(), name="sync-manifest"),
    path("sync/operations/", SyncOperationsBatchAPIView.as_view(), name="sync-operations"),
]
