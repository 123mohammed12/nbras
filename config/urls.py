from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("api/v1/notifications/", include("apps.notifications.urls")),
    # ─── Admin ────────────────────────────────────
    path("admin/", admin.site.urls),

    # ─── Operations Console (ADM-01) ──────────────
    path("control/", include("apps.control.urls", namespace="control")),

    # ─── API v1: Phase 1 Accounts & Locations ──────
    path("api/v1/auth/", include("apps.accounts.urls.auth_urls")),
    path("api/v1/me/", include("apps.accounts.urls.user_urls")),
    path("api/v1/locations/", include("apps.locations.urls")),

    # ─── API v1: Phase 2 Core Apps ──────────────────
    path("api/v1/curriculum/", include("apps.curriculum.api.urls", namespace="curriculum")),
    path("api/v1/content/", include("apps.content.api.urls", namespace="content")),
    path("api/v1/", include("apps.question_bank.api.urls", namespace="question_bank")),
    path("api/v1/", include("apps.ministerial_exams.api.urls", namespace="ministerial_exams")),
    path("api/v1/", include("apps.assessments.api.urls", namespace="assessments")),
    path("api/v1/", include("apps.attempts.api.urls", namespace="attempts")),
    path("api/v1/", include("apps.progress.api.urls", namespace="progress")),
    path("api/v1/", include("apps.analytics.api.urls", namespace="analytics")),
    path("api/v1/", include("apps.subscriptions.api.urls", namespace="subscriptions")),
    path("api/v1/", include("apps.synchronization.api.urls", namespace="synchronization")),
    path("api/v1/", include("apps.media_access.urls", namespace="media_access")),
    path("api/v1/downloads/", include("apps.downloads.urls", namespace="downloads")),

    # ─── API Docs ─────────────────────────────────
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    from apps.media_access.public_views import public_media
    urlpatterns += static(settings.MEDIA_URL, view=public_media)
