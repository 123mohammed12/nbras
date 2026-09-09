from django.db import models
from django.conf import settings
from apps.progress.models.status import ProgressStatus


class LessonProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progresses")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.CASCADE)
    
    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED, db_index=True)
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    mastery_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    best_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    latest_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    attempts_count = models.PositiveIntegerField(default=0)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    
    last_activity_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    mastered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "progress_lesson_progresses"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "lesson"],
                name="unique_lesson_progress_per_enrollment",
            )
        ]
        verbose_name = "تقدم الدرس"
        verbose_name_plural = "تقدم الدروس"

    def __str__(self):
        return f"{self.user} - {self.lesson.title} ({self.completion_percentage}%)"


class UnitProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="unit_progresses")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.CASCADE)
    
    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED, db_index=True)
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    mastery_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    lessons_completed = models.PositiveIntegerField(default=0)
    lessons_total = models.PositiveIntegerField(default=0)
    
    best_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    latest_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    attempts_count = models.PositiveIntegerField(default=0)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    
    last_activity_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "progress_unit_progresses"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "unit"],
                name="unique_unit_progress_per_enrollment",
            )
        ]
        verbose_name = "تقدم الوحدة"
        verbose_name_plural = "تقدم الوحدات"


class SubjectProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subject_progresses")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.CASCADE)
    
    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED, db_index=True)
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    mastery_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    units_completed = models.PositiveIntegerField(default=0)
    units_total = models.PositiveIntegerField(default=0)
    
    best_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    latest_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    attempts_count = models.PositiveIntegerField(default=0)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    
    last_activity_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "progress_subject_progresses"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "subject"],
                name="unique_subject_progress_per_enrollment",
            )
        ]
        verbose_name = "تقدم المادة"
        verbose_name_plural = "تقدم المواد"
