from django.db import models


class ProgressStatus(models.TextChoices):
    NOT_STARTED = "not_started", "لم يبدأ"
    IN_PROGRESS = "in_progress", "قيد التقدم"
    COMPLETED = "completed", "مكتمل"
    MASTERED = "mastered", "متمكن"
    NEEDS_REVIEW = "needs_review", "يحتاج مراجعة"
