import uuid
from django.db import models


class AttemptProgressReceipt(models.Model):
    """
    Receipt to ensure idempotent processing of attempts for progress.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.OneToOneField("attempts.AssessmentAttempt", on_delete=models.CASCADE, related_name="progress_receipt")
    
    progress_version = models.IntegerField(default=1)
    analytics_event_id = models.CharField(max_length=255, null=True, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "progress_attempt_receipts"
        verbose_name = "إيصال تقدم المحاولة"
        verbose_name_plural = "إيصالات تقدم المحاولات"
