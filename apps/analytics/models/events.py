import uuid
from django.db import models
from django.conf import settings


class AnalyticsEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.CharField(max_length=255, db_index=True)
    event_type = models.CharField(max_length=50, db_index=True)
    schema_version = models.CharField(max_length=10, default="1.0")
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analytics_events")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    
    source_type = models.CharField(max_length=50, blank=True, default="")
    source_id = models.CharField(max_length=200, blank=True, default="")
    
    attempt = models.ForeignKey("attempts.AssessmentAttempt", on_delete=models.SET_NULL, null=True, blank=True)
    
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True)
    
    occurred_at = models.DateTimeField(db_index=True)
    payload = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_events"
        constraints = [
            models.UniqueConstraint(
                fields=["event_id"],
                name="unique_analytics_event_id",
            ),
            models.UniqueConstraint(
                fields=["event_type", "attempt"],
                condition=models.Q(
                    event_type="assessment_submitted",
                    attempt__isnull=False,
                ),
                name="unique_assessment_submitted_event_per_attempt",
            )
        ]
        verbose_name = "حدث تحليلي"
        verbose_name_plural = "أحداث تحليلية"


class DailyLearningSummary(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_learning_summaries")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    date = models.DateField(db_index=True)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True)
    
    learning_seconds = models.PositiveIntegerField(default=0)
    resources_started = models.PositiveIntegerField(default=0)
    resources_completed = models.PositiveIntegerField(default=0)
    
    attempts_submitted = models.PositiveIntegerField(default=0)
    questions_answered = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    
    points_earned = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    points_possible = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analytics_daily_summaries"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "date", "subject"],
                condition=models.Q(subject__isnull=False),
                name="unique_daily_subject_summary",
            ),
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "date"],
                condition=models.Q(subject__isnull=True),
                name="unique_daily_overall_summary",
            ),
        ]
        verbose_name = "ملخص التعلم اليومي"
        verbose_name_plural = "ملخصات التعلم اليومية"
