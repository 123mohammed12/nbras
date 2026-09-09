"""
Authentication and Dashboard views for the Operations Console (/control/).
"""

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.generic import TemplateView

from apps.control.permissions import StaffRequiredMixin
from apps.control.services.dashboard import get_dashboard_metrics


class ControlLoginForm(AuthenticationForm):
    """
    Staff login form enforcing phone number as username and is_staff verification.
    """
    error_messages = {
        "invalid_login": "رقم الهاتف أو كلمة المرور غير صحيحة.",
        "inactive": "هذا الحساب معطل حالياً.",
        "not_staff": "عذراً، هذا الحساب ليس لديه صلاحيات الوصول لمنصة العمليات.",
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError(
                self.error_messages["not_staff"],
                code="not_staff",
            )


class ControlLoginView(View):
    """
    Staff login view at /control/login/.
    """
    template_name = "control/login.html"

    def get(self, request):
        if request.user.is_authenticated and request.user.is_staff:
            next_url = request.GET.get("next") or reverse_lazy("control:dashboard")
            return redirect(next_url)
        form = ControlLoginForm(request=request)
        return render(request, self.template_name, {"form": form})

    @method_decorator(csrf_protect)
    def post(self, request):
        form = ControlLoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next") or reverse_lazy("control:dashboard")
            return redirect(next_url)
        return render(request, self.template_name, {"form": form})


class ControlLogoutView(View):
    """
    Staff logout view.
    """
    @method_decorator(csrf_protect)
    def post(self, request):
        logout(request)
        messages.info(request, "تم تسجيل الخروج بنجاح.")
        return redirect("control:login")

    def get(self, request):
        # Fallback redirect to login
        return redirect("control:login")


class DashboardView(StaffRequiredMixin, TemplateView):
    """
    Main operational dashboard view at /control/.
    """
    template_name = "control/dashboard.html"

    def get_template_names(self):
        if self.request.headers.get("HX-Request") or self.request.GET.get("fragment") == "kpis":
            return ["control/partials/dashboard_kpis.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metrics = get_dashboard_metrics(self.request.user)
        context.update({
            "page_title": "لوحة التحكم التشغيلية",
            "active_tab": "dashboard",
            "metrics": metrics,
        })
        return context
