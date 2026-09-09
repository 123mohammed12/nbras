import uuid
from django.db import models
from django.conf import settings
from apps.progress.models.status import ProgressStatus


class LearningResourceProgress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learning_resource_progresses")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    
    resource_type = models.CharField(max_length=50, db_index=True)
    resource_id = models.CharField(max_length=200, db_index=True)
    
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED, db_index=True)
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    
    started_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    resource_snapshot = models.JSONField(default=dict, blank=True)
    source_version = models.CharField(max_length=50, blank=True, default="")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "progress_learning_resource_progresses"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "resource_type", "resource_id"],
                name="unique_resource_progress_per_enrollment",
            )
        ]
        verbose_name = "تقدم المورد التعليمي"
        verbose_name_plural = "تقدم الموارد التعليمية"


class SessionStatus(models.TextChoices):
    ACTIVE = "active", "نشط"
    COMPLETED = "completed", "مكتمل"
    ABANDONED = "abandoned", "مهجور"
    EXPIRED = "expired", "منتهي"


class LearningSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learning_sessions")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    
    client_session_id = models.CharField(max_length=255, db_index=True)
    
    resource_type = models.CharField(max_length=50, blank=True, default="")
    resource_id = models.CharField(max_length=200, blank=True, default="")
    
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=SessionStatus.choices, default=SessionStatus.ACTIVE)
    total_items = models.PositiveIntegerField(default=0)
    current_position = models.PositiveIntegerField(default=0)
    session_state = models.JSONField(default=dict, blank=True)
    
    started_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "progress_learning_sessions"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "client_session_id"],
                name="unique_learning_session_per_user",
            )
        ]
        verbose_name = "جلسة التعلم"
        verbose_name_plural = "جلسات التعلم"


class SmartCardRating(models.TextChoices):
    AGAIN = "again", "تحتاج مراجعة"
    HARD = "hard", "بصعوبة"
    GOOD = "good", "عرفتها"


class SmartCardReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        LearningSession,
        on_delete=models.CASCADE,
        related_name="smart_card_reviews",
    )
    card = models.ForeignKey(
        "content.Flashcard",
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    rating = models.CharField(max_length=20, choices=SmartCardRating.choices)
    client_event_id = models.CharField(max_length=255)
    reviewed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "progress_smart_card_reviews"
        ordering = ["reviewed_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "client_event_id"],
                name="unique_smart_card_review_event_per_session",
            ),
            models.UniqueConstraint(
                fields=["session", "card"],
                name="unique_smart_card_review_per_session_card",
            ),
        ]
        verbose_name = "مراجعة بطاقة ذكية"
        verbose_name_plural = "مراجعات البطاقات الذكية"
