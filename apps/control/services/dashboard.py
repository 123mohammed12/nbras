"""
Operational dashboard data aggregation service.
Queries real, indexed data sources with isolated error handling and performance bounding.
"""

import logging
from datetime import timedelta
from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone

from apps.curriculum.models import ContentStatus
from apps.question_bank.models import Question, QuestionVersion
from apps.analytics.models import QuestionQualityAggregate
from apps.imports.models import ContentImportLog
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.accounts.models import UserDevice
from apps.notifications.models import PushDelivery
from apps.question_bank.health import pool_health

logger = logging.getLogger("control.dashboard")


class DashboardMetricsService:
    """Service encapsulating dashboard KPI aggregation and error isolation."""

    @staticmethod
    def _get_pool_health():
        cached_health = cache.get("control_dashboard_pool_health")
        if cached_health is None:
            cached_health = pool_health(row_limit=50)
            cache.set("control_dashboard_pool_health", cached_health, timeout=300)

        rows = cached_health.get("rows", [])
        eligible_total = cached_health.get("eligible_total", 0)
        unhealthy = sum(1 for r in rows if r.get("count", 0) < 5)
        return {
            "healthy": unhealthy == 0,
            "eligible_total": eligible_total,
            "total_rules": len(rows),
            "unhealthy_rules": unhealthy,
            "rows": rows[:10],
            "details": f"{eligible_total} أسئلة مؤهلة عبر {len(rows)} قاعدة",
            "is_available": True,
        }

    @classmethod
    def get_dashboard_metrics(cls, user=None):
        now = timezone.now()
        now_24h = now - timedelta(hours=24)
        now_7d = now - timedelta(days=7)

        metrics = {
            "generated_at": now,
            "questions_under_review": 0,
            "questions_awaiting_review": 0,
            "published_questions_count": 0,
            "published_questions_total": 0,
            "published_questions_by_subject": [],
            "published_by_subject": [],
            "quality_flagged_count": 0,
            "quality_alerts_count": 0,
            "imports_24h": {
                "total": 0,
                "succeeded": 0,
                "completed": 0,
                "failed": 0,
                "pending": 0,
                "recent_logs": [],
            },
            "active_subscriptions_count": 0,
            "active_students_7d": 0,
            "active_students_7d_count": 0,
            "notifications_24h": {
                "total": 0,
                "sent": 0,
                "pending": 0,
                "failed": 0,
                "is_available": True,
            },
            "pool_health": {
                "healthy": True,
                "eligible_total": 0,
                "total_rules": 0,
                "unhealthy_rules": 0,
                "rows": [],
                "details": "جاهز",
                "is_available": True,
            },
            "errors": {},
        }

        # 1. الأسئلة بانتظار المراجعة (QuestionVersion status = under_review)
        try:
            under_review_count = QuestionVersion.objects.filter(
                status=ContentStatus.UNDER_REVIEW
            ).count()
            metrics["questions_under_review"] = under_review_count
            metrics["questions_awaiting_review"] = under_review_count
        except Exception as exc:
            logger.exception("Failed to query questions_under_review")
            metrics["errors"]["questions_under_review"] = str(exc)

        # 2. الأسئلة المنشورة (Published Questions Total & Subject Distribution)
        try:
            published_total = Question.objects.filter(
                status=ContentStatus.PUBLISHED
            ).count()
            metrics["published_questions_count"] = published_total
            metrics["published_questions_total"] = published_total

            by_subject = list(
                Question.objects.filter(status=ContentStatus.PUBLISHED)
                .values("subject__name_ar")
                .annotate(count=Count("id"))
                .order_by("-count")[:8]
            )
            # Normalize key for template rendering
            formatted_subjects = [
                {"subject_name": item["subject__name_ar"] or "عام", "count": item["count"]}
                for item in by_subject
            ]
            metrics["published_questions_by_subject"] = formatted_subjects
            metrics["published_by_subject"] = formatted_subjects
        except Exception as exc:
            logger.exception("Failed to query published_questions")
            metrics["errors"]["published_questions"] = str(exc)

        # 3. تنبيهات جودة الأسئلة (QuestionQualityAggregate flagged items)
        try:
            flagged_count = QuestionQualityAggregate.objects.exclude(
                quality_flags=[]
            ).count()
            metrics["quality_flagged_count"] = flagged_count
            metrics["quality_alerts_count"] = flagged_count
        except Exception as exc:
            logger.exception("Failed to query quality_alerts")
            metrics["errors"]["quality_alerts"] = str(exc)

        # 4. عمليات الاستيراد خلال آخر 24 ساعة
        try:
            recent_24h = ContentImportLog.objects.filter(created_at__gte=now_24h)
            total_imports = recent_24h.count()
            failed_imports = recent_24h.filter(status="failed").count()
            completed_imports = recent_24h.filter(status__in=["succeeded", "completed"]).count()
            pending_imports = recent_24h.filter(status__in=["pending", "in_progress"]).count()

            recent_logs = list(
                ContentImportLog.objects.select_related("created_by")
                .order_by("-created_at")[:5]
            )

            metrics["imports_24h"] = {
                "total": total_imports,
                "succeeded": completed_imports,
                "completed": completed_imports,
                "failed": failed_imports,
                "pending": pending_imports,
                "recent_logs": recent_logs,
            }
        except Exception as exc:
            logger.exception("Failed to query imports_24h")
            metrics["errors"]["imports_24h"] = str(exc)

        # 5. الاشتراكات النشطة (Active Subscriptions)
        try:
            metrics["active_subscriptions_count"] = Subscription.objects.filter(
                status=SubscriptionStatus.ACTIVE,
                expires_at__gte=now,
            ).count()
        except Exception as exc:
            logger.exception("Failed to query active_subscriptions")
            metrics["errors"]["active_subscriptions"] = str(exc)

        # 6. الطلاب المتفاعلون خلال آخر 7 أيام
        try:
            active_students = (
                UserDevice.objects.filter(
                    last_seen_at__gte=now_7d,
                    user__is_staff=False,
                )
                .values("user_id")
                .distinct()
                .count()
            )
            metrics["active_students_7d"] = active_students
            metrics["active_students_7d_count"] = active_students
        except Exception as exc:
            logger.exception("Failed to query active_students_7d")
            metrics["errors"]["active_students_7d"] = str(exc)

        # 7. حالة تسليم الإشعارات خلال آخر 24 ساعة
        try:
            push_qs = PushDelivery.objects.filter(created_at__gte=now_24h)
            metrics["notifications_24h"]["total"] = push_qs.count()
            metrics["notifications_24h"]["sent"] = push_qs.filter(status="SENT").count()
            metrics["notifications_24h"]["pending"] = push_qs.filter(status="PENDING").count()
            metrics["notifications_24h"]["failed"] = push_qs.filter(status="FAILED").count()
        except Exception as exc:
            logger.warning("PushDelivery table query failed: %s", exc)
            metrics["notifications_24h"]["is_available"] = False
            metrics["errors"]["notifications_24h"] = str(exc)

        # 8. جاهزية بنك الأسئلة (Pool Health)
        try:
            metrics["pool_health"] = cls._get_pool_health()
        except Exception as exc:
            logger.exception("Failed to calculate pool_health")
            metrics["pool_health"] = {
                "healthy": False,
                "eligible_total": 0,
                "total_rules": 0,
                "unhealthy_rules": 0,
                "rows": [],
                "details": "غير متاح مؤقتاً",
                "is_available": False,
            }
            metrics["errors"]["pool_health"] = str(exc)

        return metrics


def get_dashboard_metrics(user=None):
    """Top-level convenience function delegating to DashboardMetricsService."""
    return DashboardMetricsService.get_dashboard_metrics(user=user)
