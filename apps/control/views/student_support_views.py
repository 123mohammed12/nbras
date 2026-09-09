"""
Operational views for Student Support Workspace (ADM-08).
Allows authorized support staff to search students, inspect profiles, view enrollments,
diagnose access and subscriptions, inspect devices, manage sessions safely, and view
learning support snapshots.
"""

import logging
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from apps.accounts.models import StudentProfile, User, UserDevice, UserSession
from apps.accounts.services.session_service import revoke_all_sessions, revoke_session
from apps.attempts.models import AssessmentAttempt
from apps.control.permissions import ControlPermissionRequiredMixin
from apps.curriculum.models import ContentStatus, Grade, StudyEnrollment, Subject
from apps.entitlements.models import UserEntitlement
from apps.entitlements.services.access_service import check_resources_access_batch
from apps.progress.models.aggregates import LessonProgress, SubjectProgress, UnitProgress
from apps.subscriptions.models import Subscription, SubscriptionStatus

logger = logging.getLogger("control.student_support")


def mask_ip_safe(ip: str | None) -> str:
    """Mask IP address to prevent exposing raw IPs to support staff."""
    if not ip:
        return "—"
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.***"
    if ":" in ip:
        # IPv6
        segments = ip.split(":")
        return f"{segments[0]}:****:****"
    return "***.***.***"


def mask_identifier_safe(val: str | None, length: int = 8) -> str:
    """Mask hardware/installation identifier for support-safe display."""
    if not val:
        return "—"
    if len(val) <= length:
        return val
    return f"{val[:length]}…"


class StudentSearchView(ControlPermissionRequiredMixin, View):
    """
    Server-side search for students supporting phone, public_code, and full name.
    Bounded query with select_related/prefetch_related to prevent N+1 queries.
    """

    permission_required = "accounts.view_studentprofile"

    def get(self, request):
        query = request.GET.get("q", "").strip()
        account_type = request.GET.get("account_type", "").strip()
        status_filter = request.GET.get("status", "").strip()
        grade_id = request.GET.get("grade_id", "").strip()

        now = timezone.now()

        qs = (
            User.objects.all()
            .select_related("student_profile")
            .prefetch_related(
                Prefetch(
                    "study_enrollments",
                    queryset=StudyEnrollment.objects.filter(is_active=True).select_related(
                        "grade", "section", "academic_year"
                    ),
                    to_attr="active_enrollments",
                ),
                Prefetch(
                    "subscriptions",
                    queryset=Subscription.objects.filter(
                        status=SubscriptionStatus.ACTIVE,
                        expires_at__gt=now,
                    ).select_related("plan"),
                    to_attr="active_subs",
                ),
            )
            .order_by("-created_at")
        )

        if query:
            qs = qs.filter(
                Q(phone__icontains=query)
                | Q(public_code__iexact=query)
                | Q(student_profile__full_name__icontains=query)
            )

        if account_type in [User.AccountType.GUEST, User.AccountType.REGISTERED]:
            qs = qs.filter(account_type=account_type)

        if status_filter == "active":
            qs = qs.filter(is_active=True)
        elif status_filter == "inactive":
            qs = qs.filter(is_active=False)

        if grade_id:
            qs = qs.filter(
                study_enrollments__grade_id=grade_id,
                study_enrollments__is_active=True,
            )

        paginator = Paginator(qs, 20)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        # Attach helper attributes for template display
        for user_obj in page_obj:
            active_enrs = getattr(user_obj, "active_enrollments", [])
            user_obj.current_enrollment = active_enrs[0] if active_enrs else None
            active_subs = getattr(user_obj, "active_subs", [])
            user_obj.current_subscription = active_subs[0] if active_subs else None

        grades = Grade.objects.filter(is_active=True).order_by("sort_order", "name_ar")

        context = {
            "active_tab": "students",
            "page_obj": page_obj,
            "query": query,
            "account_type": account_type,
            "status_filter": status_filter,
            "grade_id": grade_id,
            "grades": grades,
            "total_count": paginator.count,
        }
        return render(request, "control/students/list.html", context)


class StudentDetailView(ControlPermissionRequiredMixin, View):
    """
    Comprehensive support profile for a student:
    - Identity & StudentProfile
    - Academic Enrollment
    - Subscription & Access Diagnostics
    - Device Inspector (privacy-aware, push tokens never exposed)
    - Sessions Workspace (revocation, masked IP, no refresh secrets)
    - Learning Support Snapshot (Read-only progress & attempts)
    """

    permission_required = "accounts.view_studentprofile"

    def get(self, request, user_id):
        student = get_object_or_404(
            User.objects.select_related(
                "student_profile",
                "student_profile__governorate",
                "student_profile__district",
                "student_profile__isolation",
                "student_profile__school",
            ),
            pk=user_id,
        )

        now = timezone.now()

        # 1. Academic Enrollment
        enrollment = (
            StudyEnrollment.objects.filter(user=student, is_active=True)
            .select_related("grade", "section", "academic_year")
            .order_by("-updated_at")
            .first()
        )
        enrollment_history = (
            StudyEnrollment.objects.filter(user=student)
            .select_related("grade", "section", "academic_year")
            .order_by("-created_at")[:5]
        )

        # 2. Subscriptions & Entitlements
        subscriptions = list(
            Subscription.objects.filter(user=student)
            .select_related("plan", "academic_year", "activated_by")
            .prefetch_related("selected_subjects")
            .order_by("-created_at")
        )
        active_subscription = next(
            (s for s in subscriptions if s.status == SubscriptionStatus.ACTIVE and s.expires_at > now),
            None,
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

            if subjects.exists():
                resources_to_check = [
                    {"resource_type": "subject", "resource_id": str(s.id), "name": s.name_ar}
                    for s in subjects
                ]
                batch_results = check_resources_access_batch(
                    user=student, enrollment=enrollment, resources=resources_to_check
                )
                for s in subjects:
                    dec = batch_results.get(("subject", str(s.id)))
                    diagnostic_results.append(
                        {
                            "subject": s,
                            "allowed": dec.allowed if dec else False,
                            "reason_code": dec.reason_code if dec else "UNKNOWN",
                            "source": dec.source if dec else "-",
                        }
                    )

        # 3. Devices Workspace (Sanitized, NO push tokens)
        devices = list(
            UserDevice.objects.filter(user=student).order_by("-last_seen_at")
        )
        for dev in devices:
            dev.safe_installation_id = mask_identifier_safe(dev.installation_id)

        # 4. Sessions Workspace (Sanitized, NO refresh token hash, NO raw IP)
        raw_sessions = list(
            UserSession.objects.filter(user=student)
            .select_related("device")
            .order_by("-created_at")
        )
        sessions = []
        active_session_count = 0
        for sess in raw_sessions:
            is_active_sess = sess.is_active
            if is_active_sess:
                active_session_count += 1
            sessions.append(
                {
                    "id": sess.id,
                    "device": sess.device,
                    "created_at": sess.created_at,
                    "last_used_at": sess.last_used_at,
                    "expires_at": sess.expires_at,
                    "revoked_at": sess.revoked_at,
                    "is_active": is_active_sess,
                    "masked_ip": mask_ip_safe(sess.last_ip),
                    "user_agent_short": (sess.user_agent[:45] + "…") if len(sess.user_agent) > 45 else (sess.user_agent or "—"),
                }
            )

        # 5. Learning Support Snapshot (Read-only)
        recent_attempts = list(
            AssessmentAttempt.objects.filter(user=student)
            .select_related("assessment", "blueprint", "dynamic_subject")
            .order_by("-started_at")[:10]
        )
        recent_lesson_progress = list(
            LessonProgress.objects.filter(user=student)
            .select_related("lesson", "lesson__unit", "lesson__unit__subject")
            .order_by("-last_activity_at")[:10]
        )
        unit_progress_list = list(
            UnitProgress.objects.filter(user=student)
            .select_related("unit", "unit__subject")
            .order_by("-last_activity_at")[:6]
        )
        subject_progress_list = list(
            SubjectProgress.objects.filter(user=student)
            .select_related("subject")
            .order_by("-last_activity_at")[:6]
        )

        context = {
            "active_tab": "students",
            "student": student,
            "enrollment": enrollment,
            "enrollment_history": enrollment_history,
            "subscriptions": subscriptions,
            "active_subscription": active_subscription,
            "user_entitlements": user_entitlements,
            "diagnostic_results": diagnostic_results,
            "devices": devices,
            "sessions": sessions,
            "active_session_count": active_session_count,
            "recent_attempts": recent_attempts,
            "recent_lesson_progress": recent_lesson_progress,
            "unit_progress_list": unit_progress_list,
            "subject_progress_list": subject_progress_list,
            "now": now,
        }
        return render(request, "control/students/detail.html", context)


class StudentSessionRevokeView(ControlPermissionRequiredMixin, View):
    """
    Safely revoke a single user session using Domain Service.
    POST-only, requires CSRF and accounts.revoke_usersession permission.
    """

    permission_required = "accounts.revoke_usersession"

    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(["POST"])

    def post(self, request, user_id, session_id):
        student = get_object_or_404(User, pk=user_id)
        revoked = revoke_session(session_id=str(session_id), user=student)

        if revoked:
            messages.success(request, "تم سحب الجلسة المحددة بنجاح.")
            from apps.control.models import ControlAuditLog
            from apps.control.services.audit_service import record_control_action
            record_control_action(
                action=ControlAuditLog.ActionChoices.SESSION_REVOKE,
                target_type="user_session",
                target_id=str(session_id),
                target_repr=f"جلسة الطالب {student.phone or student.public_code}",
                reason="سحب جلسة من مساحة دعم الطلاب",
                request=request,
            )
            logger.info("Session %s revoked for user %s by staff %s", session_id, student.pk, request.user.pk)
        else:
            messages.info(request, "الجلسة مسحوبة مسبقاً أو غير موجودة.")

        return redirect("control:student_detail", user_id=student.id)


class StudentSessionRevokeAllView(ControlPermissionRequiredMixin, View):
    """
    Safely revoke ALL user sessions using Domain Service.
    POST-only, requires CSRF and accounts.revoke_usersession permission.
    """

    permission_required = "accounts.revoke_usersession"

    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(["POST"])

    def post(self, request, user_id):
        student = get_object_or_404(User, pk=user_id)
        count = revoke_all_sessions(user=student)

        from apps.control.models import ControlAuditLog
        from apps.control.services.audit_service import record_control_action
        record_control_action(
            action=ControlAuditLog.ActionChoices.SESSION_REVOKE_ALL,
            target_type="user",
            target_id=str(student.id),
            target_repr=f"كافة جلسات الطالب {student.phone or student.public_code}",
            reason="سحب كافة الجلسات من مساحة دعم الطلاب",
            metadata={"revoked_count": count},
            request=request,
        )

        messages.success(request, f"تم سحب جميع جلسات المستخدم بنجاح ({count} جلسة نشطة تم إلغاؤها).")
        logger.info("All sessions revoked for user %s by staff %s (count=%d)", student.pk, request.user.pk, count)

        return redirect("control:student_detail", user_id=student.id)
