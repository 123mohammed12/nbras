import logging
from django.db import transaction
from apps.accounts.models import User
from apps.analytics.models import AnalyticsEvent, DailyLearningSummary, StudentPerformanceInsight
from apps.analytics.services.insights_service import recalculate_student_insights

logger = logging.getLogger("analytics.guest_merge")


def analytics_merge_handler(source_guest: User, target_user: User) -> dict:
    """
    Merge handler for moving Analytics Events from guest to authenticated user.
    """
    stats = {
        "events_moved": 0,
        "summaries_moved": 0,
        "insights_moved": 0,
    }
    
    with transaction.atomic():
        # Move events securely
        events = AnalyticsEvent.objects.filter(user=source_guest)
        for ev in events:
            exists = AnalyticsEvent.objects.filter(event_id=ev.event_id).exists()
            if not exists:
                ev.user = target_user
                ev.save(update_fields=["user"])
                stats["events_moved"] += 1
            else:
                ev.delete()
                
        # Re-assign or recalculate summaries
        summaries = DailyLearningSummary.objects.filter(user=source_guest)
        for s in summaries:
            target_s = DailyLearningSummary.objects.filter(
                user=target_user, study_enrollment=s.study_enrollment, date=s.date, subject=s.subject
            ).first()
            if target_s:
                target_s.learning_seconds += s.learning_seconds
                target_s.resources_started += s.resources_started
                target_s.resources_completed += s.resources_completed
                target_s.attempts_submitted += s.attempts_submitted
                target_s.questions_answered += s.questions_answered
                target_s.correct_answers += s.correct_answers
                target_s.points_earned += s.points_earned
                target_s.points_possible += s.points_possible
                target_s.save()
                s.delete()
            else:
                s.user = target_user
                s.save(update_fields=["user", "updated_at"])
                stats["summaries_moved"] += 1
                
        # Insights: It's better to delete guest insights and recalculate for target
        StudentPerformanceInsight.objects.filter(user=source_guest).delete()
        
    return stats
