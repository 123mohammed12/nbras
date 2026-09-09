from django.urls import path

from apps.downloads.views import SubjectDownloadPlanView, UnitPackManifestView, UnitPayloadView

app_name = "downloads"

urlpatterns = [
    path("units/<str:unit_id>/manifest/", UnitPackManifestView.as_view(), name="unit-manifest"),
    path("units/<str:unit_id>/payload/", UnitPayloadView.as_view(), name="unit-payload"),
    path("subjects/<str:subject_id>/plan/", SubjectDownloadPlanView.as_view(), name="subject-plan"),
]

