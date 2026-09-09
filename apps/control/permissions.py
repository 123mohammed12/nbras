"""
Permission mixins and decorators for the Operations Console (/control/).
"""

from functools import wraps
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse_lazy


class StaffRequiredMixin(AccessMixin):
    """
    Verify that the current user is authenticated and is a staff member.
    Anonymous users are redirected to the staff login page.
    Authenticated non-staff users receive HTTP 403 Forbidden.
    """
    login_url = reverse_lazy("control:login")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_staff:
            raise PermissionDenied("الوصول لمنصة العمليات مخصص للمشرفين فقط.")
        return super().dispatch(request, *args, **kwargs)


class ControlPermissionRequiredMixin(StaffRequiredMixin):
    """
    Verify that the user is staff AND has the required permission(s).
    Super Admin (is_superuser=True) automatically bypasses permission checks.
    """
    permission_required = None

    def get_permission_required(self):
        if self.permission_required is None:
            return []
        if isinstance(self.permission_required, str):
            return [self.permission_required]
        return list(self.permission_required)

    def has_permission(self):
        if self.request.user.is_superuser:
            return True
        perms = self.get_permission_required()
        if not perms:
            return True
        return self.request.user.has_perms(perms)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_staff:
            raise PermissionDenied("الوصول لمنصة العمليات مخصص للمشرفين فقط.")
        if not self.has_permission():
            raise PermissionDenied("ليس لديك الصلاحية المطلوبة للوصول إلى هذه الصفحة.")
        return super().dispatch(request, *args, **kwargs)


def control_staff_required(view_func):
    """
    Decorator for function-based views in /control/.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse_lazy('control:login')}?next={request.path}")
        if not request.user.is_staff:
            raise PermissionDenied("الوصول لمنصة العمليات مخصص للمشرفين فقط.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view


class SuperuserRequiredMixin(StaffRequiredMixin):
    """
    Verify that the current user is authenticated and is a superuser (Super Admin).
    Staff members without is_superuser=True receive HTTP 403 Forbidden.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_superuser:
            raise PermissionDenied("هذه الصفحة مخصصة لمدير النظام الرئيسي فقط.")
        return super().dispatch(request, *args, **kwargs)

