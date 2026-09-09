"""
Super Admin boundary enforcement for Django Admin (/admin/).

Restricts access to /admin/ strictly to Super Administrators (is_superuser=True).
Staff non-superusers (is_staff=True, is_superuser=False) are rejected with
PermissionDenied (HTTP 403 Forbidden).
"""

from functools import wraps
from django.contrib import admin
from django.core.exceptions import PermissionDenied


def apply_admin_boundary():
    """
    Apply Super Admin restrictions to the default admin.site instance.
    Idempotent: will not double-patch.
    """
    site = admin.site
    if getattr(site, "_superadmin_boundary_applied", False):
        return

    original_admin_view = site.admin_view

    def superuser_has_permission(request):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_superuser
        )

    def superuser_admin_view(view, cacheable=False):
        wrapped = original_admin_view(view, cacheable=cacheable)

        @wraps(wrapped)
        def inner(request, *args, **kwargs):
            if request.user.is_authenticated and not request.user.is_superuser:
                raise PermissionDenied(
                    "عذراً، لوحة الإدارة التقنية (/admin/) مخصصة للمشرفين الفنيين (Super Admin) فقط. يرجى استخدام منصة العمليات (/control/)."
                )
            return wrapped(request, *args, **kwargs)

        return inner

    site.has_permission = superuser_has_permission
    site.admin_view = superuser_admin_view
    site._superadmin_boundary_applied = True
