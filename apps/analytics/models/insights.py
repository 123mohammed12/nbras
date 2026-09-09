import uuid
from django.db import models
from django.conf import settings


class InsightType(models.TextChoices):
    STRENGTH = "strength", "نقطة قوة"
    WEAKNESS = "weakness", "نقطة ضعف"
    NEEDS_REVIEW = "needs_review", "يحتاج مراجعة"
    IMPROVING = "improving", "في تحسن"


class StudentPerformanceInsight(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="performance_insights")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.SET_NULL, null=True, blank=True)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True)
    
    insight_type = models.CharField(max_length=20, choices=InsightType.choices, default=InsightType.STRENGTH, db_index=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    evidence_count = models.PositiveIntegerField(default=1)
    
    message = models.TextField()
    calculation_version = models.IntegerField(default=1)
    
    calculated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "analytics_student_insights"
        ordering = ["-calculated_at"]
        verbose_name = "تحليل أداء الطالب"
        verbose_name_plural = "تحليلات أداء الطلاب"
