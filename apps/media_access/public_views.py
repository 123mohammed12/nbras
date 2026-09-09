"""Development media serving must not expose the protected storage tree."""
from django.conf import settings
from django.http import Http404
from django.views.static import serve


PUBLIC_PREFIXES = (
    "subjects/icons/", "subjects/covers/", "curriculum/banners/",
    "curriculum/subjects/icons/", "curriculum/subjects/covers/",
)


def public_media(request, path):
    from pathlib import PurePosixPath
    normalized = PurePosixPath(path.replace("\\", "/"))
    if ".." in normalized.parts or not str(normalized).startswith(PUBLIC_PREFIXES):
        raise Http404
    return serve(request, str(normalized), document_root=settings.MEDIA_ROOT)
