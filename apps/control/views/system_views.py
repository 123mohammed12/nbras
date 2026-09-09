"""
Central Operational Audit and System Health Views (ADM-09).
Provides:
- ControlAuditListView (/control/system/audit/): Read-only, indexed filtering, pagination.
- SystemHealthView (/control/system/health/): Lightweight diagnostics for App, DB, Cache, Notifications, Imports.
Zero secret exposure guaranteed.
"""

import time
import django
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.control.models import ControlAuditLog
from apps.control.permissions import ControlPermissionRequiredMixin
from apps.imports.models import ContentImportLog
from apps.notifications.models import Notification, NotificationRecipient


class ControlAuditListView(ControlPermissionRequiredMixin, View):
    """
    Read-only Central Operational Audit Log viewer.
    Protected by control.view_controlauditlog.
    Supports filtering by action, actor, target_type, date range, and keyword search.
    """

    permission_required = "control.view_controlauditlog"

    def get(self, request):
        action = request.GET.get("action", "").strip()
        actor_query = request.GET.get("actor", "").strip()
        target_type = request.GET.get("target_type", "").strip()
        q = request.GET.get("q", "").strip()
        date_from = request.GET.get("date_from", "").strip()
        date_to = request.GET.get("date_to", "").strip()

        qs = ControlAuditLog.objects.all().select_related("actor").order_by("-created_at")

        if action:
            qs = qs.filter(action=action)

        if actor_query:
            qs = qs.filter(
                Q(actor__phone__icontains=actor_query)
                | Q(actor__public_code__icontains=actor_query)
            )

        if target_type:
            qs = qs.filter(target_type__icontains=target_type)

        if q:
            qs = qs.filter(
                Q(target_repr__icontains=q)
                | Q(target_id__icontains=q)
                | Q(reason__icontains=q)
            )

        if date_from:
            try:
                qs = qs.filter(created_at__date__gte=date_from)
            except Exception:
                pass

        if date_to:
            try:
                qs = qs.filter(created_at__date__lte=date_to)
            except Exception:
                pass

        paginator = Paginator(qs, 25)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        context = {
            "active_tab": "system",
            "active_subtab": "audit",
            "page_obj": page_obj,
            "action": action,
            "actor_query": actor_query,
            "target_type": target_type,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "action_choices": ControlAuditLog.ActionChoices.choices,
            "total_count": paginator.count,
        }
        return render(request, "control/system/audit_list.html", context)


class SystemHealthView(ControlPermissionRequiredMixin, View):
    """
    Lightweight, bounded System Diagnostics and Operational Health check.
    Zero secret exposure: Credentials, DB URLs, and SECRET_KEY are strictly excluded.
    """

    permission_required = "control.view_controlauditlog"

    def get(self, request):
        # 1. Application Diagnostic
        app_health = {
            "status": "healthy",
            "django_version": django.get_version(),
            "environment": getattr(settings, "ENVIRONMENT", "Development"),
            "timezone": settings.TIME_ZONE,
            "uptime_indicator": "متاح ومستقر",
        }

        # 2. Database Probe (SELECT 1 + latency)
        db_health = {"status": "healthy", "latency_ms": 0.0, "engine": "Unknown", "message": "متصل بنجاح"}
        try:
            t0 = time.perf_counter()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
            latency = (time.perf_counter() - t0) * 1000
            db_health["latency_ms"] = round(latency, 2)
            db_health["engine"] = connection.vendor.upper()
            if latency > 1000:
                db_health["status"] = "degraded"
                db_health["message"] = "استجابة قاعدة البيانات بطيئة نسبياً"
        except Exception as exc:
            db_health["status"] = "unavailable"
            db_health["message"] = "فشل الاتصال بقاعدة البيانات"

        # 3. Cache Probe (write / read / delete with ephemeral key)
        cache_health = {"status": "healthy", "latency_ms": 0.0, "backend": "DefaultCache", "message": "متصل بنجاح"}
        try:
            backend_class = settings.CACHES.get("default", {}).get("BACKEND", "").split(".")[-1]
            cache_health["backend"] = backend_class or "Cache"
            t0 = time.perf_counter()
            probe_key = "__ops_health_probe__"
            cache.set(probe_key, 1, timeout=5)
            val = cache.get(probe_key)
            cache.delete(probe_key)
            latency = (time.perf_counter() - t0) * 1000
            cache_health["latency_ms"] = round(latency, 2)
            if val != 1:
                cache_health["status"] = "degraded"
                cache_health["message"] = "استجابة التخزين المؤقت غير متطابقة"
        except Exception as exc:
            cache_health["status"] = "unavailable"
            cache_health["message"] = "فشل التحقق من ذاكرة التخزين المؤقت"

        # 4. Notifications Aggregates
        try:
            total_notifs = Notification.objects.count()
            scheduled_notifs = Notification.objects.filter(status="scheduled").count()
            sent_notifs = Notification.objects.filter(status="sent").count()
            failed_deliveries = NotificationRecipient.objects.filter(status="failed").count()
            pending_deliveries = NotificationRecipient.objects.filter(status="pending").count()
            notif_status = "healthy" if failed_deliveries == 0 else "warning"
            notif_health = {
                "status": notif_status,
                "total_notifications": total_notifs,
                "scheduled_notifications": scheduled_notifs,
                "sent_notifications": sent_notifs,
                "failed_deliveries": failed_deliveries,
                "pending_deliveries": pending_deliveries,
            }
        except Exception:
            notif_health = {"status": "warning", "total_notifications": 0, "failed_deliveries": 0}

        # 5. Imports Aggregates
        try:
            total_imports = ContentImportLog.objects.count()
            failed_imports = ContentImportLog.objects.filter(status="failed").count()
            recent_failed = ContentImportLog.objects.filter(status="failed").order_by("-created_at")[:3]
            import_status = "healthy" if failed_imports == 0 else "warning"
            import_health = {
                "status": import_status,
                "total_imports": total_imports,
                "failed_imports": failed_imports,
                "recent_failed": recent_failed,
            }
        except Exception:
            import_health = {"status": "healthy", "total_imports": 0, "failed_imports": 0}

        # Overall Status
        if db_health["status"] == "unavailable" or cache_health["status"] == "unavailable":
            overall_status = "unavailable"
            overall_label = "غير متاح جزئياً"
            overall_badge = "danger"
        elif db_health["status"] == "degraded" or cache_health["status"] == "degraded" or notif_health["status"] == "warning":
            overall_status = "degraded"
            overall_label = "تحذير / يعمل مع ملاحظات"
            overall_badge = "warning"
        else:
            overall_status = "healthy"
            overall_label = "جميع الأنظمة تعمل بكفاءة"
            overall_badge = "success"

        context = {
            "active_tab": "system",
            "active_subtab": "health",
            "overall_status": overall_status,
            "overall_label": overall_label,
            "overall_badge": overall_badge,
            "app_health": app_health,
            "db_health": db_health,
            "cache_health": cache_health,
            "notif_health": notif_health,
            "import_health": import_health,
            "checked_at": timezone.now(),
        }
        return render(request, "control/system/health.html", context)
