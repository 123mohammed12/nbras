import csv
from datetime import timedelta
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.models import User
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, StudyEnrollment, Subject
from apps.entitlements.models import Entitlement, FreeAccessPolicy, PlanEntitlement, UserEntitlement
from apps.entitlements.services.access_service import check_resources_access_batch
from apps.control.forms.subscription_forms import (
    ActivationCodeBatchCreateForm,
    ActivationCodeFilterForm,
    DirectActivationForm,
    FreeAccessPolicyForm,
    PlanEntitlementManageForm,
    StudentSubscriptionSearchForm,
    SubscriptionFilterForm,
    SubscriptionPlanForm,
)
from apps.control.permissions import ControlPermissionRequiredMixin, SuperuserRequiredMixin
from apps.subscriptions.models import (
    ActivationCode,
    ActivationCodeBatch,
    ActivationCodeStatus,
    ActivationCodeUsage,
    PackageTierType,
    Subscription,
    SubscriptionAudit,
    SubscriptionPlan,
    SubscriptionSource,
    SubscriptionStatus,
)
from apps.subscriptions.services.batch_service import (
    generate_activation_code_batch,
    revoke_activation_code_batch,
)
from apps.subscriptions.services.subscription_service import (
    cancel_subscription,
    direct_activate_subscription,
    preview_subscription_grant,
    revoke_subscription,
)


class SubscriptionsOverviewView(ControlPermissionRequiredMixin, View):
    """
    Overview workspace dashboard for subscriptions, activation codes, and audit logs.
    """
    permission_required = "subscriptions.view_subscription"

    def get(self, request):
        now = timezone.now()
        expiring_threshold = now + timedelta(days=7)

        # Operational KPIs
        active_count = Subscription.objects.filter(status=SubscriptionStatus.ACTIVE, expires_at__gt=now).count()
        expiring_soon_count = Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            expires_at__gt=now,
            expires_at__lte=expiring_threshold,
        ).count()
        expired_count = Subscription.objects.filter(status=SubscriptionStatus.EXPIRED).count()

        # Activation code stats
        total_batches_count = ActivationCodeBatch.objects.count()
        available_codes_count = ActivationCode.objects.filter(status=ActivationCodeStatus.AVAILABLE).count()
        redeemed_codes_count = ActivationCode.objects.filter(status=ActivationCodeStatus.REDEEMED).count()
        plans_count = SubscriptionPlan.objects.filter(is_active=True).count()

        # Recent activities
        recent_subscriptions = list(
            Subscription.objects.select_related("user", "plan", "academic_year")
            .order_by("-created_at")[:5]
        )
        recent_audits = list(
            SubscriptionAudit.objects.select_related("subscription__user", "actor")
            .order_by("-created_at")[:6]
        )

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "overview",
            "active_count": active_count,
            "expiring_soon_count": expiring_soon_count,
            "expired_count": expired_count,
            "total_batches_count": total_batches_count,
            "available_codes_count": available_codes_count,
            "redeemed_codes_count": redeemed_codes_count,
            "plans_count": plans_count,
            "recent_subscriptions": recent_subscriptions,
            "recent_audits": recent_audits,
        }
        return render(request, "control/subscriptions/overview.html", context)


class StudentSubscriptionListView(ControlPermissionRequiredMixin, View):
    """
    Search and filter students and their subscription statuses.
    """
    permission_required = "subscriptions.view_subscription"

    def get(self, request):
        form = SubscriptionFilterForm(request.GET or None)
        qs = (
            Subscription.objects.select_related(
                "user", "study_enrollment__grade", "study_enrollment__section",
                "academic_year", "plan", "activated_by",
            )
            .prefetch_related("selected_subjects")
            .order_by("-created_at")
        )

        if form.is_valid():
            status = form.cleaned_data.get("status")
            source = form.cleaned_data.get("source")
            academic_year = form.cleaned_data.get("academic_year")
            plan = form.cleaned_data.get("plan")
            q = form.cleaned_data.get("q")

            if status:
                qs = qs.filter(status=status)
            if source:
                qs = qs.filter(source=source)
            if academic_year:
                qs = qs.filter(academic_year=academic_year)
            if plan:
                qs = qs.filter(plan=plan)
            if q:
                q = q.strip()
                qs = qs.filter(
                    Q(user__phone__icontains=q)
                    | Q(user__public_code__icontains=q)
                    | Q(user__student_profile__full_name__icontains=q)
                )

        paginator = Paginator(qs, 25)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "students",
            "form": form,
            "page_obj": page_obj,
            "total_count": paginator.count,
        }
        return render(request, "control/subscriptions/students/list.html", context)


class StudentSubscriptionDetailView(ControlPermissionRequiredMixin, View):
    """
    Operational subscription profile for a student: subscriptions, grants, and live access diagnostics.
    """
    permission_required = "subscriptions.view_subscription"

    def get(self, request, user_id):
        student = get_object_or_404(User, pk=user_id)
        enrollment = (
            StudyEnrollment.objects.filter(user=student, is_active=True)
            .select_related("grade", "section", "academic_year")
            .order_by("-updated_at")
            .first()
        )

        subscriptions = list(
            Subscription.objects.filter(user=student)
            .select_related("plan", "academic_year", "activated_by")
            .prefetch_related("selected_subjects")
            .order_by("-created_at")
        )

        user_entitlements = list(
            UserEntitlement.objects.filter(user=student)
            .select_related("entitlement", "granted_by")
            .order_by("-created_at")
        )

        # Access diagnostic on curriculum subjects for this student
        diagnostic_results = []
        if enrollment:
            subjects = Subject.objects.filter(
                grade_id=enrollment.grade_id,
                section_id=enrollment.section_id,
                status=ContentStatus.PUBLISHED,
            ).order_by("sort_order", "name_ar")

            resources_to_check = [
                {"resource_type": "subject", "resource_id": str(s.id), "name": s.name_ar}
                for s in subjects
            ]
            batch_results = check_resources_access_batch(
                user=student, enrollment=enrollment, resources=resources_to_check
            )

            for s in subjects:
                dec = batch_results.get(("subject", str(s.id)))
                diagnostic_results.append({
                    "subject": s,
                    "allowed": dec.allowed if dec else False,
                    "reason_code": dec.reason_code if dec else "UNKNOWN",
                    "source": dec.source if dec else "-",
                })

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "students",
            "student": student,
            "enrollment": enrollment,
            "subscriptions": subscriptions,
            "user_entitlements": user_entitlements,
            "diagnostic_results": diagnostic_results,
        }
        return render(request, "control/subscriptions/students/detail.html", context)


class DirectActivationView(ControlPermissionRequiredMixin, View):
    """
    Direct subscription activation wizard with grant preview and explicit confirmation.
    """
    permission_required = "subscriptions.direct_activate_subscription"

    def get(self, request):
        initial = {}
        phone = request.GET.get("phone")
        plan_id = request.GET.get("plan_id")
        if phone:
            initial["student_phone"] = phone
        if plan_id:
            initial["plan"] = plan_id

        form = DirectActivationForm(initial=initial)
        context = {
            "active_tab": "subscriptions",
            "active_subtab": "direct_activate",
            "form": form,
            "preview": None,
        }
        return render(request, "control/subscriptions/activation/direct_activate.html", context)

    def post(self, request):
        form = DirectActivationForm(request.POST)
        preview = None
        user = None
        enrollment = None

        if form.is_valid():
            phone = form.cleaned_data["student_phone"]
            plan = form.cleaned_data["plan"]
            selected_subjects = list(form.cleaned_data["subjects"])
            selected_subject_ids = [str(s.id) for s in selected_subjects]
            reason = form.cleaned_data["reason"].strip()
            action = request.POST.get("action", "preview")

            user = User.objects.filter(phone=phone).first()
            if user:
                enrollment = (
                    StudyEnrollment.objects.filter(user=user, is_active=True)
                    .select_related("grade", "section", "academic_year")
                    .order_by("-updated_at")
                    .first()
                )

            if not user or not enrollment:
                form.add_error("student_phone", "لا يوجد طالب مسجل برقم الهاتف هذا أو لا يملك قيداً دراسياً نشطاً.")
            else:
                try:
                    preview = preview_subscription_grant(
                        user=user,
                        enrollment=enrollment,
                        plan=plan,
                        selected_subject_ids=selected_subject_ids,
                    )
                except ApplicationError as exc:
                    form.add_error(None, exc.message)

                if preview is not None and action == "confirm":
                    try:
                        subscription, _ = direct_activate_subscription(
                            user=user,
                            enrollment=enrollment,
                            plan=plan,
                            selected_subject_ids=selected_subject_ids,
                            actor=request.user,
                            reason=reason,
                        )
                        student_name = getattr(getattr(user, "student_profile", None), "full_name", None) or user.phone
                        from apps.control.models import ControlAuditLog
                        from apps.control.services.audit_service import record_control_action
                        record_control_action(
                            action=ControlAuditLog.ActionChoices.SUBSCRIPTION_ACTIVATE,
                            target_type="subscription",
                            target_id=str(subscription.id),
                            target_repr=f"تفعيل {plan.name} للطالب {user.phone}",
                            reason=reason,
                            metadata={"plan_id": str(plan.id), "plan_name": plan.name},
                            request=request,
                        )
                        messages.success(
                            request,
                            f"تم تفعيل باقة '{plan.name}' بنجاح للطالب {student_name}."
                        )
                        return redirect("control:student_subscription_detail", user_id=user.pk)
                    except ApplicationError as exc:
                        form.add_error(None, exc.message)

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "direct_activate",
            "form": form,
            "preview": preview,
            "student_user": user,
            "student_enrollment": enrollment,
        }
        return render(request, "control/subscriptions/activation/direct_activate.html", context)


class ActivationCodeBatchListView(ControlPermissionRequiredMixin, View):
    """
    Workspace for activation code batches.
    """
    permission_required = "subscriptions.view_activationcodebatch"

    def get(self, request):
        batches = (
            ActivationCodeBatch.objects.select_related("plan", "created_by")
            .annotate(
                available_count=Count("codes", filter=Q(codes__status=ActivationCodeStatus.AVAILABLE)),
                redeemed_count=Count("codes", filter=Q(codes__status=ActivationCodeStatus.REDEEMED)),
                revoked_count=Count("codes", filter=Q(codes__status=ActivationCodeStatus.REVOKED)),
                expired_count=Count("codes", filter=Q(codes__status=ActivationCodeStatus.EXPIRED)),
            )
            .order_by("-created_at")
        )

        paginator = Paginator(batches, 20)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "codes",
            "page_obj": page_obj,
        }
        return render(request, "control/subscriptions/codes/batch_list.html", context)


class ActivationCodeBatchCreateView(ControlPermissionRequiredMixin, View):
    """
    Generate an activation code batch with one-time raw code display and CSV export.
    """
    permission_required = "subscriptions.generate_code_batch"

    def get(self, request):
        form = ActivationCodeBatchCreateForm()
        return render(request, "control/subscriptions/codes/generate.html", {
            "active_tab": "subscriptions",
            "active_subtab": "codes",
            "form": form,
        })

    def post(self, request):
        form = ActivationCodeBatchCreateForm(request.POST)
        if form.is_valid():
            try:
                batch, raw_codes = generate_activation_code_batch(
                    plan=form.cleaned_data["plan"],
                    quantity=form.cleaned_data["quantity"],
                    batch_code=form.cleaned_data["batch_code"],
                    code_expires_at=form.cleaned_data["code_expires_at"],
                    actor=request.user,
                )

                from apps.control.models import ControlAuditLog
                from apps.control.services.audit_service import record_control_action
                record_control_action(
                    action=ControlAuditLog.ActionChoices.CODE_BATCH_GENERATE,
                    target_type="activation_code_batch",
                    target_id=str(batch.id),
                    target_repr=f"توليد دفعة رموز: {batch.batch_code} ({batch.quantity} رمز)",
                    metadata={"quantity": batch.quantity, "plan_id": str(batch.plan_id)},
                    request=request,
                )

                if request.POST.get("export") == "csv":
                    response = HttpResponse(content_type="text/csv; charset=utf-8")
                    response["Content-Disposition"] = f'attachment; filename="codes_{batch.batch_code}.csv"'
                    response.write("\ufeff")  # UTF-8 BOM
                    writer = csv.writer(response)
                    writer.writerow(["رقم الدفعة", "اسم الباقة", "رمز التفعيل الخام"])
                    for code in raw_codes:
                        writer.writerow([batch.batch_code, batch.plan.name, code])
                    return response

                # Render one-time success view
                return render(request, "control/subscriptions/codes/generated_success.html", {
                    "active_tab": "subscriptions",
                    "active_subtab": "codes",
                    "batch": batch,
                    "raw_codes": raw_codes,
                    "total_count": len(raw_codes),
                })
            except ApplicationError as exc:
                form.add_error(None, exc.message)

        return render(request, "control/subscriptions/codes/generate.html", {
            "active_tab": "subscriptions",
            "active_subtab": "codes",
            "form": form,
        })


class ActivationCodeListView(ControlPermissionRequiredMixin, View):
    """
    Lookup and inspect masked activation codes.
    """
    permission_required = "subscriptions.view_activationcode"

    def get(self, request):
        form = ActivationCodeFilterForm(request.GET or None)
        qs = ActivationCode.objects.select_related("plan", "batch", "created_by").order_by("-created_at")

        if form.is_valid():
            batch = form.cleaned_data.get("batch")
            plan = form.cleaned_data.get("plan")
            status = form.cleaned_data.get("status")
            q = form.cleaned_data.get("q")

            if batch:
                qs = qs.filter(batch=batch)
            if plan:
                qs = qs.filter(plan=plan)
            if status:
                qs = qs.filter(status=status)
            if q:
                q = q.strip()
                qs = qs.filter(
                    Q(display_code_masked__icontains=q)
                    | Q(batch_code__icontains=q)
                    | Q(batch__batch_code__icontains=q)
                )

        paginator = Paginator(qs, 30)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "code_lookup",
            "form": form,
            "page_obj": page_obj,
            "total_count": paginator.count,
        }
        return render(request, "control/subscriptions/codes/code_list.html", context)


class ActivationCodeUsageDetailView(ControlPermissionRequiredMixin, View):
    """
    Detail inspection of a redeemed activation code and its usage.
    """
    permission_required = "subscriptions.view_activationcode"

    def get(self, request, pk):
        code = get_object_or_404(ActivationCode.objects.select_related("plan", "batch"), pk=pk)
        usage = ActivationCodeUsage.objects.filter(activation_code=code).select_related(
            "user", "study_enrollment", "subscription__plan"
        ).first()

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "code_lookup",
            "code": code,
            "usage": usage,
        }
        return render(request, "control/subscriptions/codes/usage_detail.html", context)


class SubscriptionAuditListView(ControlPermissionRequiredMixin, View):
    """
    Audit timeline of subscription events.
    """
    permission_required = "subscriptions.view_subscription"

    def get(self, request):
        audits = (
            SubscriptionAudit.objects.select_related("subscription__user", "actor")
            .order_by("-created_at")
        )

        paginator = Paginator(audits, 25)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "audit",
            "page_obj": page_obj,
        }
        return render(request, "control/subscriptions/audit/list.html", context)


# ==============================================================================
# SUPER ADMIN ONLY COMMERCIAL & POLICY CONTROLS
# ==============================================================================

class SubscriptionPlanListView(SuperuserRequiredMixin, View):
    """
    Super Admin commercial plans manager.
    """
    def get(self, request):
        plans = (
            SubscriptionPlan.objects.select_related("academic_year", "grade", "section")
            .annotate(
                active_subs=Count("user_subscriptions", filter=Q(user_subscriptions__status=SubscriptionStatus.ACTIVE)),
                total_subs=Count("user_subscriptions"),
            )
            .order_by("sort_order", "name")
        )

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "plans",
            "plans": plans,
        }
        return render(request, "control/subscriptions/plans/list.html", context)


class SubscriptionPlanCreateView(SuperuserRequiredMixin, View):
    """
    Super Admin create new commercial plan.
    """
    def get(self, request):
        form = SubscriptionPlanForm()
        return render(request, "control/subscriptions/plans/form.html", {
            "active_tab": "subscriptions",
            "active_subtab": "plans",
            "form": form,
            "is_create": True,
        })

    def post(self, request):
        form = SubscriptionPlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"تم إنشاء الخطة '{plan.name}' بنجاح.")
            return redirect("control:subscription_plan_list")
        return render(request, "control/subscriptions/plans/form.html", {
            "active_tab": "subscriptions",
            "active_subtab": "plans",
            "form": form,
            "is_create": True,
        })


class SubscriptionPlanEditView(SuperuserRequiredMixin, View):
    """
    Super Admin edit existing commercial plan.
    """
    def get(self, request, pk):
        plan = get_object_or_404(SubscriptionPlan, pk=pk)
        form = SubscriptionPlanForm(instance=plan)
        return render(request, "control/subscriptions/plans/form.html", {
            "active_tab": "subscriptions",
            "active_subtab": "plans",
            "form": form,
            "plan": plan,
            "is_create": False,
        })

    def post(self, request, pk):
        plan = get_object_or_404(SubscriptionPlan, pk=pk)
        form = SubscriptionPlanForm(request.POST, instance=plan)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"تم حفظ تعديلات الخطة '{plan.name}' بنجاح.")
            return redirect("control:subscription_plan_list")
        return render(request, "control/subscriptions/plans/form.html", {
            "active_tab": "subscriptions",
            "active_subtab": "plans",
            "form": form,
            "plan": plan,
            "is_create": False,
        })


class PlanEntitlementManageView(SuperuserRequiredMixin, View):
    """
    Super Admin mapping of PlanEntitlements for a plan.
    """
    def get(self, request, plan_id):
        plan = get_object_or_404(SubscriptionPlan, pk=plan_id)
        current_entitlement_ids = list(
            PlanEntitlement.objects.filter(plan=plan).values_list("entitlement_id", flat=True)
        )
        form = PlanEntitlementManageForm(initial={"entitlements": current_entitlement_ids})

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "plans",
            "plan": plan,
            "form": form,
        }
        return render(request, "control/subscriptions/plans/entitlements.html", context)

    def post(self, request, plan_id):
        plan = get_object_or_404(SubscriptionPlan, pk=plan_id)
        form = PlanEntitlementManageForm(request.POST)
        if form.is_valid():
            selected_entitlements = form.cleaned_data["entitlements"]
            with transaction.atomic():
                PlanEntitlement.objects.filter(plan=plan).delete()
                for ent in selected_entitlements:
                    PlanEntitlement.objects.create(plan=plan, entitlement=ent)
            messages.success(request, f"تم تحديث استحقاقات الخطة '{plan.name}' بنجاح.")
            return redirect("control:subscription_plan_list")

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "plans",
            "plan": plan,
            "form": form,
        }
        return render(request, "control/subscriptions/plans/entitlements.html", context)


class FreeAccessPolicyListView(SuperuserRequiredMixin, View):
    """
    Super Admin view and manager for FreeAccessPolicy records.
    """
    def get(self, request):
        policies = (
            FreeAccessPolicy.objects.select_related("grade", "section", "subject", "academic_year", "free_unit")
            .order_by("grade__sort_order", "section__sort_order", "subject__sort_order")
        )

        context = {
            "active_tab": "subscriptions",
            "active_subtab": "free_policy",
            "policies": policies,
        }
        return render(request, "control/subscriptions/free_policy/list.html", context)


class FreeAccessPolicyEditView(SuperuserRequiredMixin, View):
    """
    Super Admin create/edit for FreeAccessPolicy.
    """
    def get(self, request, pk=None):
        policy = get_object_or_404(FreeAccessPolicy, pk=pk) if pk else None
        form = FreeAccessPolicyForm(instance=policy)
        return render(request, "control/subscriptions/free_policy/form.html", {
            "active_tab": "subscriptions",
            "active_subtab": "free_policy",
            "form": form,
            "policy": policy,
            "is_create": policy is None,
        })

    def post(self, request, pk=None):
        policy = get_object_or_404(FreeAccessPolicy, pk=pk) if pk else None
        form = FreeAccessPolicyForm(request.POST, instance=policy)
        if form.is_valid():
            policy = form.save()
            messages.success(request, f"تم حفظ سياسة الوصول المجاني ({policy}) بنجاح.")
            return redirect("control:free_policy_list")

        return render(request, "control/subscriptions/free_policy/form.html", {
            "active_tab": "subscriptions",
            "active_subtab": "free_policy",
            "form": form,
            "policy": policy,
            "is_create": policy is None,
        })


class ActivationCodeBatchRevokeView(SuperuserRequiredMixin, View):
    """
    Super Admin bulk revocation of available codes in a batch.
    """
    def post(self, request, batch_id):
        batch = get_object_or_404(ActivationCodeBatch, pk=batch_id)
        reason = request.POST.get("reason", "").strip() or "إلغاء إداري من قبل مدير النظام"

        try:
            revoked_count = revoke_activation_code_batch(
                batch=batch, actor=request.user, reason=reason
            )
            from apps.control.models import ControlAuditLog
            from apps.control.services.audit_service import record_control_action
            record_control_action(
                action=ControlAuditLog.ActionChoices.CODE_BATCH_REVOKE,
                target_type="activation_code_batch",
                target_id=str(batch.id),
                target_repr=f"إلغاء دفعة رموز: {batch.batch_code}",
                reason=reason,
                metadata={"revoked_count": revoked_count},
                request=request,
            )
            messages.success(
                request,
                f"تم إلغاء {revoked_count} رمز متاح في الدفعة '{batch.batch_code}' بنجاح."
            )
        except ApplicationError as exc:
            messages.error(request, exc.message)

        return redirect("control:activation_code_batch_list")


class SubscriptionRevokeView(SuperuserRequiredMixin, View):
    """
    Super Admin revocation or cancellation of a student subscription.
    """
    def post(self, request, subscription_id):
        sub = get_object_or_404(Subscription, pk=subscription_id)
        action_type = request.POST.get("action_type", "revoke")
        reason = request.POST.get("reason", "").strip() or "إجراء إداري من قبل مدير النظام"

        with transaction.atomic():
            before_state = {
                "status": sub.status,
                "plan_id": str(sub.plan_id),
                "is_all_subjects": sub.is_all_subjects,
            }
            if action_type == "cancel":
                cancel_subscription(sub)
                action_name = "cancel"
            else:
                revoke_subscription(sub)
                action_name = "revoke"

            after_state = {
                "status": sub.status,
                "plan_id": str(sub.plan_id),
                "is_all_subjects": sub.is_all_subjects,
            }

            SubscriptionAudit.objects.create(
                subscription=sub,
                action=action_name,
                source=SubscriptionSource.ADMIN,
                actor=request.user,
                reason=reason,
                before_state=before_state,
                after_state=after_state,
            )

            from apps.control.models import ControlAuditLog
            from apps.control.services.audit_service import record_control_action
            record_control_action(
                action=ControlAuditLog.ActionChoices.SUBSCRIPTION_REVOKE,
                target_type="subscription",
                target_id=str(sub.id),
                target_repr=f"إلغاء/سحب اشتراك {sub.plan.name} للطالب {sub.user.phone}",
                reason=reason,
                metadata={"action_type": action_type},
                request=request,
            )

        messages.success(request, f"تم تغيير حالة الاشتراك إلى {sub.get_status_display()} بنجاح.")
        return redirect("control:student_subscription_detail", user_id=sub.user_id)
