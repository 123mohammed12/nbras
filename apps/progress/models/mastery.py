from django.conf import settings
from django.db import models


class MasteryScopeType(models.TextChoices):
    SUBJECT = "subject", "Subject"
    UNIT = "unit", "Unit"
    LESSON = "lesson", "Lesson"


class MasteryAggregate(models.Model):
    """Rebuildable AR-08 read model; attempts and question evidence remain authoritative."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mastery_aggregates",
    )
    study_enrollment = models.ForeignKey(
        "curriculum.StudyEnrollment",
        on_delete=models.CASCADE,
        related_name="mastery_aggregates",
    )
    scope_type = models.CharField(max_length=12, choices=MasteryScopeType.choices)
    scope_id = models.CharField(max_length=64)
    mastery_score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    distinct_evidence_count = models.PositiveIntegerField(default=0)
    effective_evidence = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    confidence = models.CharField(max_length=20, default="insufficient")
    trend = models.CharField(max_length=20, default="insufficient_data")
    weakness_status = models.CharField(max_length=30, default="unknown")
    weakness_priority = models.CharField(max_length=20, blank=True, default="")
    weakness_reason = models.CharField(max_length=120, blank=True, default="")
    source_breakdown = models.JSONField(default=dict, blank=True)
    difficulty_breakdown = models.JSONField(default=dict, blank=True)
    question_type_breakdown = models.JSONField(default=dict, blank=True)
    policy_version = models.CharField(max_length=30)
    calculated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "progress_mastery_aggregates"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "scope_type", "scope_id"],
                name="unique_mastery_scope_per_enrollment",
            )
        ]
        indexes = [
            models.Index(
                fields=["user", "study_enrollment", "scope_type"],
                name="progress_mastery_scope_idx",
            )
        ]
