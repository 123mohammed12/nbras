import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.models import User
from apps.control.forms.notification_forms import NotificationDraftForm, describe_action_destination
from apps.control.permissions import ControlPermissionRequiredMixin
from apps.curriculum.models import Grade, Section, Subject, Unit, Lesson
from apps.content.models import Summary, FlashcardDeck
from apps.notifications.actions import validate_action
from apps.notifications.models import (
    Notification,
    NotificationRecipient,
    PushDelivery,
    PushDevice,
)
from apps.notifications.services import (
    audience_users,
    cancel,
    materialize_batch,
    schedule,
)

logger = logging.getLogger("control.notifications")


class NotificationsOverviewView(ControlPermissionRequiredMixin, View):
    """
    Dashboard overview for operational notifications: KPIs, delivery statistics, recent campaigns.
    """
    permission_required = "notifications.view_notification"

    def get(self, request):
        now = timezone.now()

        # Notification status metrics
        notif_stats = Notification.objects.aggregate(
            total=models.Count("id"),
            draft=models.Count("id", filter=models.Q(status=Notification.Status.DRAFT)),
            scheduled=models.Count("id", filter=models.Q(status=Notification.Status.SCHEDULED)),
            publishing=models.Count("id", filter=models.Q(status=Notification.Status.PUBLISHING)),
            published=models.Count("id", filter=models.Q(status=Notification.Status.PUBLISHED)),
            cancelled=models.Count("id", filter=models.Q(status=Notification.Status.CANCELLED)),
            expired=models.Count("id", filter=models.Q(status=Notification.Status.EXPIRED)),
        )

        # Delivery metrics
        delivery_stats = PushDelivery.objects.aggregate(
            total=models.Count("id"),
            pending=models.Count("id", filter=models.Q(status="PENDING")),
            sent=models.Count("id", filter=models.Q(status="SENT")),
            failed=models.Count("id", filter=models.Q(status="FAILED")),
            skipped=models.Count("id", filter=models.Q(status="SKIPPED")),
        )

        sent_count = delivery_stats["sent"] or 0
        failed_count = delivery_stats["failed"] or 0
        attempted = sent_count + failed_count
        success_rate = round((sent_count / attempted * 100), 1) if attempted > 0 else 0.0

        # Recent campaigns
        recent_notifications = (
            Notification.objects.select_related("grade", "section", "subject", "created_by")
            .annotate(recipients_count=models.Count("recipients", distinct=True))
            .order_by("-created_at")[:8]
        )

        context = {
            "active_tab": "notifications",
            "active_subtab": "overview",
            "notif_stats": notif_stats,
            "delivery_stats": delivery_stats,
            "success_rate": success_rate,
            "recent_notifications": recent_notifications,
        }
        return render(request, "control/notifications/overview.html", context)


class NotificationListView(ControlPermissionRequiredMixin, View):
    """
    Searchable, filterable, paginated browser of platform notifications.
    """
    permission_required = "notifications.view_notification"

    def get(self, request):
        qs = Notification.objects.select_related("grade", "section", "subject", "created_by").annotate(
            recipients_count=models.Count("recipients", distinct=True)
        )

        # Filtering
        q = request.GET.get("q", "").strip()
        status = request.GET.get("status", "").strip()
        category = request.GET.get("category", "").strip()
        priority = request.GET.get("priority", "").strip()
        audience = request.GET.get("audience", "").strip()

        if q:
            qs = qs.filter(models.Q(title__icontains=q) | models.Q(body__icontains=q))
        if status:
            qs = qs.filter(status=status)
        if category:
            qs = qs.filter(category=category)
        if priority:
            qs = qs.filter(priority=priority)
        if audience:
            qs = qs.filter(audience=audience)

        paginator = Paginator(qs.order_by("-created_at"), 15)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "active_tab": "notifications",
            "active_subtab": "list",
            "page_obj": page_obj,
            "q": q,
            "status": status,
            "category": category,
            "priority": priority,
            "audience": audience,
            "status_choices": Notification.Status.choices,
            "category_choices": Notification.Category.choices,
            "priority_choices": [("LOW", "منخفض"), ("NORMAL", "عادي"), ("HIGH", "مرتفع")],
            "audience_choices": Notification.Audience.choices,
        }
        return render(request, "control/notifications/list.html", context)


class NotificationCreateView(ControlPermissionRequiredMixin, View):
    """
    Drafting and scheduling wizard for operational notifications.
    """
    permission_required = "notifications.add_notification"

    def get(self, request):
        form = NotificationDraftForm()
        context = {
            "active_tab": "notifications",
            "active_subtab": "create",
            "form": form,
            "is_edit": False,
        }
        return render(request, "control/notifications/form.html", context)

    def post(self, request):
        form = NotificationDraftForm(request.POST)
        action_intent = request.POST.get("action_intent", "save_draft")

        if form.is_valid():
            notification = form.save(commit=True, actor=request.user)

            if action_intent == "schedule_now":
                if not (request.user.has_perm("notifications.publish_notification") or request.user.is_superuser):
                    raise PermissionDenied("ليس لديك صلاحية جدولة ونشر الإشعارات.")
                try:
                    schedule(notification.id)
                    now = timezone.now()
                    if notification.publish_at and notification.publish_at <= now:
                        materialize_batch(notification.id)
                    messages.success(request, f"تمت جدولة ونشر الإشعار '{notification.title}' بنجاح.")
                except ValidationError as e:
                    msg = e.messages[0] if hasattr(e, "messages") else str(e)
                    messages.warning(request, f"تم حفظ المسودة، ولكن تعذرت الجدولة: {msg}")
                    return redirect("control:notification_edit", pk=notification.pk)

                return redirect("control:notification_detail", pk=notification.pk)

            messages.success(request, f"تم حفظ مسودة الإشعار '{notification.title}' بنجاح.")
            return redirect("control:notification_detail", pk=notification.pk)

        context = {
            "active_tab": "notifications",
            "active_subtab": "create",
            "form": form,
            "is_edit": False,
        }
        return render(request, "control/notifications/form.html", context)


class NotificationEditView(ControlPermissionRequiredMixin, View):
    """
    Editing an existing draft notification.
    """
    permission_required = "notifications.change_notification"

    def get(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk)
        if notification.status != Notification.Status.DRAFT:
            messages.warning(request, "لا يمكن تعديل إشعار تم جدولته أو نشره بالفعل.")
            return redirect("control:notification_detail", pk=notification.pk)

        form = NotificationDraftForm(instance=notification)
        context = {
            "active_tab": "notifications",
            "active_subtab": "list",
            "form": form,
            "notification": notification,
            "is_edit": True,
        }
        return render(request, "control/notifications/form.html", context)

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk)
        if notification.status != Notification.Status.DRAFT:
            messages.error(request, "لا يمكن تعديل إشعار غير مسودة.")
            return redirect("control:notification_detail", pk=notification.pk)

        form = NotificationDraftForm(request.POST, instance=notification)
        action_intent = request.POST.get("action_intent", "save_draft")

        if form.is_valid():
            notification = form.save(commit=True)

            if action_intent == "schedule_now":
                if not (request.user.has_perm("notifications.publish_notification") or request.user.is_superuser):
                    raise PermissionDenied("ليس لديك صلاحية جدولة ونشر الإشعارات.")
                try:
                    schedule(notification.id)
                    now = timezone.now()
                    if notification.publish_at and notification.publish_at <= now:
                        materialize_batch(notification.id)
                    messages.success(request, f"تمت جدولة ونشر الإشعار '{notification.title}' بنجاح.")
                except ValidationError as e:
                    msg = e.messages[0] if hasattr(e, "messages") else str(e)
                    messages.warning(request, f"تم حفظ التعديلات، ولكن تعذرت الجدولة: {msg}")
                    return redirect("control:notification_edit", pk=notification.pk)

                return redirect("control:notification_detail", pk=notification.pk)

            messages.success(request, f"تم تحديث مسودة الإشعار '{notification.title}' بنجاح.")
            return redirect("control:notification_detail", pk=notification.pk)

        context = {
            "active_tab": "notifications",
            "active_subtab": "list",
            "form": form,
            "notification": notification,
            "is_edit": True,
        }
        return render(request, "control/notifications/form.html", context)


class NotificationDetailView(ControlPermissionRequiredMixin, View):
    """
    Detailed inspection of a notification, its audience, semantic action, and push delivery analytics.
    """
    permission_required = "notifications.view_notification"

    def get(self, request, pk):
        notification = get_object_or_404(
            Notification.objects.select_related("grade", "section", "subject", "created_by"),
            pk=pk,
        )

        recipients_count = notification.recipients.count()

        # Push delivery statistics for this notification
        delivery_qs = PushDelivery.objects.filter(recipient__notification=notification)
        delivery_stats = delivery_qs.aggregate(
            total=models.Count("id"),
            pending=models.Count("id", filter=models.Q(status="PENDING")),
            sent=models.Count("id", filter=models.Q(status="SENT")),
            failed=models.Count("id", filter=models.Q(status="FAILED")),
            skipped=models.Count("id", filter=models.Q(status="SKIPPED")),
        )

        sent_count = delivery_stats["sent"] or 0
        failed_count = delivery_stats["failed"] or 0
        attempted = sent_count + failed_count
        success_rate = round((sent_count / attempted * 100), 1) if attempted > 0 else 0.0

        # Top error codes (aggregated safely)
        top_errors = (
            delivery_qs.filter(status="FAILED")
            .exclude(error_code="")
            .values("error_code")
            .annotate(count=models.Count("id"))
            .order_by("-count")[:5]
        )

        # Recent safe diagnostic delivery samples (paginated, ZERO raw token exposure)
        diagnostic_deliveries = (
            delivery_qs.select_related("recipient__user", "push_device__device")
            .order_by("-created_at")[:15]
        )

        action_label = describe_action_destination(notification.action_type, notification.action_payload)

        context = {
            "active_tab": "notifications",
            "active_subtab": "list",
            "notification": notification,
            "recipients_count": recipients_count,
            "delivery_stats": delivery_stats,
            "success_rate": success_rate,
            "top_errors": top_errors,
            "diagnostic_deliveries": diagnostic_deliveries,
            "action_label": action_label,
        }
        return render(request, "control/notifications/detail.html", context)


class NotificationScheduleView(ControlPermissionRequiredMixin, View):
    """
    Transactional execution of schedule/publish operation on a draft notification.
    """
    permission_required = "notifications.publish_notification"

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk)
        if notification.status != Notification.Status.DRAFT:
            messages.error(request, "يمكن فقط جدولة ونشر الإشعارات الموجودة في حالة المسودة.")
            return redirect("control:notification_detail", pk=pk)

        try:
            notification = schedule(notification.id)
            now = timezone.now()
            from apps.control.models import ControlAuditLog
            from apps.control.services.audit_service import record_control_action

            if notification.publish_at and notification.publish_at <= now:
                count = materialize_batch(notification.id)
                messages.success(request, f"تم نشر الإشعار فورياً بنجاح وإعداد {count} مستلماً.")
                action_choice = ControlAuditLog.ActionChoices.NOTIFICATION_PUBLISH
            else:
                messages.success(request, f"تمت جدولة الإشعار بنجاح للنشر في {notification.publish_at}.")
                action_choice = ControlAuditLog.ActionChoices.NOTIFICATION_SCHEDULE

            record_control_action(
                action=action_choice,
                target_type="notification",
                target_id=str(notification.id),
                target_repr=notification.title,
                metadata={"publish_at": str(notification.publish_at), "audience": notification.audience},
                request=request,
            )
        except ValidationError as e:
            msg = e.messages[0] if hasattr(e, "messages") else str(e)
            messages.error(request, f"تعذرت جدولة الإشعار: {msg}")

        return redirect("control:notification_detail", pk=pk)


class NotificationCancelView(ControlPermissionRequiredMixin, View):
    """
    Transactional cancellation of a draft or scheduled notification.
    """
    permission_required = "notifications.publish_notification"

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk)
        if notification.status not in (Notification.Status.DRAFT, Notification.Status.SCHEDULED):
            messages.error(request, "يمكن فقط إلغاء المسودات أو الإشعارات المجدولة قبل البدء في تجهيزها.")
            return redirect("control:notification_detail", pk=pk)

        try:
            cancel(notification.id)
            from apps.control.models import ControlAuditLog
            from apps.control.services.audit_service import record_control_action
            record_control_action(
                action=ControlAuditLog.ActionChoices.NOTIFICATION_CANCEL,
                target_type="notification",
                target_id=str(notification.id),
                target_repr=notification.title,
                request=request,
            )
            messages.success(request, f"تم إلغاء الإشعار '{notification.title}' بنجاح.")
        except ValidationError as e:
            msg = e.messages[0] if hasattr(e, "messages") else str(e)
            messages.error(request, f"تعذر إلغاء الإشعار: {msg}")

        return redirect("control:notification_detail", pk=pk)


class AudienceEstimateView(ControlPermissionRequiredMixin, View):
    """
    Live server-side audience estimator endpoint for HTMX live count.
    Never exposes recipient lists to JavaScript; returns calculated count and safety state.
    """
    permission_required = "notifications.view_notification"

    def get_or_post(self, request):
        params = request.POST if request.method == "POST" else request.GET

        audience = params.get("audience", "").strip()
        grade_id = params.get("grade", "").strip() or None
        section_id = params.get("section", "").strip() or None
        subject_id = params.get("subject", "").strip() or None
        selected_users = params.get("selected_users", "").strip()

        estimated_count = 0
        is_valid = True
        warning_msg = ""

        if not audience:
            return render(
                request,
                "control/notifications/partials/recipient_estimate.html",
                {"count": 0, "is_valid": False, "warning": "اختر نوع الجمهور أولاً لحساب العدد المتوقع."},
            )

        try:
            subj = None
            if subject_id:
                subj = Subject.objects.filter(pk=subject_id).first()

            # Temporary in-memory notification
            n = Notification(
                audience=audience,
                grade_id=grade_id or (subj.grade_id if subj else None),
                section_id=section_id or (subj.section_id if subj else None),
                subject=subj,
            )
            if subj:
                n.subject_id = subj.id

            if audience in (Notification.Audience.GRADE, Notification.Audience.SECTION) and not n.grade_id:
                is_valid = False
                warning_msg = "يرجى اختيار الصف الدراسي لإتمام الحساب."
            elif audience == Notification.Audience.SECTION and not n.section_id:
                is_valid = False
                warning_msg = "يرجى اختيار المسار الدراسي لإتمام الحساب."
            elif audience in (Notification.Audience.SUBJECT, Notification.Audience.SUBJECT_ACCESS) and not subj:
                is_valid = False
                warning_msg = "يرجى اختيار المادة الدراسية لإتمام الحساب."
            elif audience == Notification.Audience.USERS:
                user_ids = [uid.strip() for uid in selected_users.split(",") if uid.strip()]
                if not user_ids:
                    is_valid = False
                    warning_msg = "لم يتم تحديد أي مستخدم حتى الآن."
                else:
                    estimated_count = User.objects.filter(pk__in=user_ids, is_active=True, is_staff=False).count()
            else:
                if audience == Notification.Audience.SUBJECT_ACCESS:
                    from apps.entitlements.services.access_service import check_resource_access
                    candidates = list(audience_users(n)[:200])
                    estimated_count = sum(
                        1 for u in candidates
                        if check_resource_access(user=u, resource_type="subject", resource_id=subj.id).allowed
                    )
                    if len(candidates) == 200:
                        warning_msg = "تقدير مقيد بعينة أولية لأداء أفضل."
                else:
                    estimated_count = audience_users(n).count()

        except Exception as e:
            is_valid = False
            warning_msg = "حدث خطأ أثناء احتساب الجمهور المستهدف."
            logger.exception("Audience estimation error: %s", e)

        context = {
            "count": estimated_count,
            "is_valid": is_valid,
            "warning": warning_msg,
            "audience": audience,
        }
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or "hx-request" in request.headers:
            return render(request, "control/notifications/partials/recipient_estimate.html", context)

        return JsonResponse({"count": estimated_count, "is_valid": is_valid, "warning": warning_msg})

    def get(self, request):
        return self.get_or_post(request)

    def post(self, request):
        return self.get_or_post(request)


class UserSearchAPIView(ControlPermissionRequiredMixin, View):
    """
    Safe autocomplete/search endpoint for large user selection (Audience: USERS).
    Limits results to 15 records and exposes only safe operational fields.
    """
    permission_required = "notifications.view_notification"

    def get(self, request):
        q = request.GET.get("q", "").strip()
        if len(q) < 2:
            return JsonResponse({"results": []})

        users = (
            User.objects.filter(is_active=True, is_staff=False)
            .filter(
                models.Q(phone__icontains=q)
                | models.Q(public_code__icontains=q)
                | models.Q(first_name__icontains=q)
                | models.Q(last_name__icontains=q)
            )
            .only("id", "phone", "public_code", "first_name", "last_name", "account_type")
            .order_by("phone")[:15]
        )

        results = [
            {
                "id": str(u.id),
                "phone": u.phone,
                "public_code": u.public_code or "-",
                "name": u.get_full_name() or u.phone,
                "account_type": "مسجل" if u.account_type == "registered" else "زائر",
            }
            for u in users
        ]
        return JsonResponse({"results": results})


class ActionDestinationPreviewView(ControlPermissionRequiredMixin, View):
    """
    Validates and renders a human-friendly label for a semantic action destination on the fly.
    """
    permission_required = "notifications.view_notification"

    def get_or_post(self, request):
        if request.method == "POST":
            try:
                data = json.loads(request.body.decode("utf-8")) if request.body else {}
            except Exception:
                data = {}
            action_type = data.get("action_type", "NONE")
            payload = data.get("payload", {})
        else:
            action_type = request.GET.get("action_type", "NONE")
            raw_payload = request.GET.get("action_payload", "{}")
            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else {}
            except Exception:
                payload = {}

        try:
            validate_action(action_type, payload)
            label = describe_action_destination(action_type, payload)
            return JsonResponse({"valid": True, "label": label, "error": None})
        except ValidationError as e:
            msg = e.message_dict.get("action_payload", ["الوجهة غير صالحة."])[0] if hasattr(e, "message_dict") else str(e)
            return JsonResponse({"valid": False, "label": None, "error": msg})
        except Exception:
            return JsonResponse({"valid": False, "label": None, "error": "تعذر التحقق من الوجهة الدلالية."})

    def get(self, request):
        return self.get_or_post(request)

    def post(self, request):
        return self.get_or_post(request)
