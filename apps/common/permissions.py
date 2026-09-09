"""
Custom permission classes for the Smart Teacher platform.
"""

from rest_framework.permissions import BasePermission


class IsOwnerOrReadOnly(BasePermission):
    """Object-level permission: only the owning user can modify."""

    def has_object_permission(self, request, view, obj):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        # Check common FK name patterns
        owner = getattr(obj, "user", None) or getattr(obj, "student", None)
        return owner == request.user


class IsRegisteredUser(BasePermission):
    """Only registered (non-guest) users can access."""
    message = "يجب إكمال تسجيل الحساب أولاً."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.account_type == "registered"
        )


class IsGuestUser(BasePermission):
    """Only guest users can access (e.g., registration completion)."""

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.account_type == "guest"
        )
