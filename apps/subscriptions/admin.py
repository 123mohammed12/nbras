from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse

from apps.accounts.models import User
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import StudyEnrollment
from apps.entitlements.models import PlanEntitlement
from apps.subscriptions.forms import (
    ActivationCodeBatchGenerationForm,
    DirectSubscriptionActivationForm,
)
from apps.subscriptions.models import (
    ActivationCode, ActivationCodeBatch, ActivationCodeStatus,
    ActivationCodeUsage, FreeGenerationUse, GeneratedQuestionUse,
    Subscription, SubscriptionAudit, SubscriptionPlan,
)
from apps.subscriptions.services.subscription_service import (
    direct_activate_subscription,
    preview_subscription_grant,
)
from apps.subscriptions.services.batch_service import generate_activation_code_batch


class PlanEntitlementInline(admin.TabularInline):
    model = PlanEntitlement
    extra = 0
    autocomplete_fields = ["entitlement"]


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ["name", "academic_year", "grade", "section", "tier_type", "subject_limit", "price", "offer_price", "currency", "is_catalog_visible", "is_active"]
    list_filter = ["academic_year", "grade", "section", "tier_type", "is_catalog_visible", "is_active"]
    search_fields = ["name", "code"]
    autocomplete_fields = ["academic_year", "grade", "section"]
    inlines = [PlanEntitlementInline]


@admin.register(ActivationCodeBatch)
class ActivationCodeBatchAdmin(admin.ModelAdmin):
    change_list_template = "admin/subscriptions/activationcodebatch/change_list.html"
    list_display = ["batch_code", "plan", "quantity", "available", "redeemed", "revoked", "created_by", "created_at"]
    search_fields = ["batch_code", "plan__name"]
    autocomplete_fields = ["plan", "created_by"]
    readonly_fields = ["created_at"]

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        return [
            path(
                "generate/",
                self.admin_site.admin_view(self.generate_view),
                name="subscriptions_activationcodebatch_generate",
            ),
        ] + super().get_urls()

    def generate_view(self, request):
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        form = ActivationCodeBatchGenerationForm(request.POST or None)
        batch = None
        raw_codes = None
        if request.method == "POST" and form.is_valid():
            try:
                batch, raw_codes = generate_activation_code_batch(
                    plan=form.cleaned_data["plan"],
                    quantity=form.cleaned_data["quantity"],
                    batch_code=form.cleaned_data["batch_code"],
                    code_expires_at=form.cleaned_data["code_expires_at"],
                    actor=request.user,
                )
            except ApplicationError as exc:
                form.add_error(None, exc.message)
        return render(
            request,
            "admin/subscriptions/activationcodebatch/generate.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "إنشاء دفعة رموز تفعيل",
                "form": form,
                "batch": batch,
                "raw_codes": raw_codes,
            },
        )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            available_count=Count("codes", filter=Q(codes__status=ActivationCodeStatus.AVAILABLE)),
            redeemed_count=Count("codes", filter=Q(codes__status=ActivationCodeStatus.REDEEMED)),
            revoked_count=Count("codes", filter=Q(codes__status=ActivationCodeStatus.REVOKED)),
        )

    @admin.display(ordering="available_count")
    def available(self, obj): return obj.available_count
    @admin.display(ordering="redeemed_count")
    def redeemed(self, obj): return obj.redeemed_count
    @admin.display(ordering="revoked_count")
    def revoked(self, obj): return obj.revoked_count


@admin.register(ActivationCode)
class ActivationCodeAdmin(admin.ModelAdmin):
    list_display = ["display_code_masked", "plan", "batch", "status", "expires_at", "created_at"]
    list_filter = ["status", "plan", "batch"]
    search_fields = ["display_code_masked", "batch_code", "batch__batch_code"]
    readonly_fields = ["code_hash", "hash_version", "display_code_masked", "used_count"]
    autocomplete_fields = ["plan", "batch", "created_by"]
    actions = ["revoke_codes"]

    @admin.action(description="إلغاء الرموز المتاحة المحددة")
    def revoke_codes(self, request, queryset):
        queryset.filter(status=ActivationCodeStatus.AVAILABLE).update(status=ActivationCodeStatus.REVOKED)


class SubscriptionAuditInline(admin.TabularInline):
    model = SubscriptionAudit
    extra = 0
    can_delete = False
    readonly_fields = ["action", "source", "actor", "reason", "before_state", "after_state", "created_at"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    change_list_template = "admin/subscriptions/subscription/change_list.html"
    list_display = ["user", "academic_year", "plan", "is_all_subjects", "status", "expires_at", "source", "activated_by"]
    list_filter = ["academic_year", "status", "source", "is_all_subjects"]
    search_fields = ["user__phone", "user__public_code", "plan__name"]
    readonly_fields = [
        "user", "study_enrollment", "academic_year", "plan", "status",
        "starts_at", "expires_at", "selected_subjects", "is_all_subjects",
        "source", "activated_at", "activated_by", "activation_code_usage",
        "commercial_snapshot", "created_at", "updated_at",
    ]
    inlines = [SubscriptionAuditInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path(
                "direct-activate/",
                self.admin_site.admin_view(self.direct_activate_view),
                name="subscriptions_subscription_direct_activate",
            ),
        ] + super().get_urls()

    def direct_activate_view(self, request):
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        form = DirectSubscriptionActivationForm(request.POST or None)
        preview = None
        if request.method == "POST" and form.is_valid():
            user = User.objects.filter(phone=form.cleaned_data["student_phone"].strip()).first()
            enrollment = (
                StudyEnrollment.objects.filter(user=user, is_active=True)
                .order_by("-updated_at")
                .first()
                if user else None
            )
            if not user or not enrollment:
                form.add_error("student_phone", "لا يوجد طالب بملف دراسي نشط لهذا الرقم.")
            else:
                try:
                    preview = preview_subscription_grant(
                        user=user,
                        enrollment=enrollment,
                        plan=form.cleaned_data["plan"],
                        selected_subject_ids=[str(item.id) for item in form.cleaned_data["subjects"]],
                    )
                except ApplicationError as exc:
                    form.add_error(None, exc.message)
                if preview is not None and request.POST.get("action") == "confirm":
                    try:
                        subscription, _ = direct_activate_subscription(
                            user=user,
                            enrollment=enrollment,
                            plan=form.cleaned_data["plan"],
                            selected_subject_ids=[str(item.id) for item in form.cleaned_data["subjects"]],
                            actor=request.user,
                            reason=form.cleaned_data["reason"],
                        )
                    except ApplicationError as exc:
                        form.add_error(None, exc.message)
                    else:
                        self.message_user(request, "تم تفعيل الباقة وتسجيل العملية في سجل التدقيق.", messages.SUCCESS)
                        return HttpResponseRedirect(
                            reverse("admin:subscriptions_subscription_change", args=[subscription.pk])
                        )
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "تفعيل باقة مباشرة",
            "form": form,
            "preview": preview,
        }
        return render(
            request,
            "admin/subscriptions/subscription/direct_activate.html",
            context,
        )


@admin.register(ActivationCodeUsage)
class ActivationCodeUsageAdmin(admin.ModelAdmin):
    list_display = ["user", "activation_code", "subscription", "used_at", "request_id"]
    search_fields = ["user__phone", "activation_code__display_code_masked"]
    readonly_fields = ["activation_code", "user", "study_enrollment", "subscription", "used_at", "request_id", "idempotency_key"]


@admin.register(SubscriptionAudit)
class SubscriptionAuditAdmin(admin.ModelAdmin):
    list_display = ["subscription", "action", "source", "actor", "created_at"]
    list_filter = ["action", "source"]
    readonly_fields = ["subscription", "action", "source", "actor", "reason", "before_state", "after_state", "created_at"]


admin.site.register(GeneratedQuestionUse)
admin.site.register(FreeGenerationUse)
