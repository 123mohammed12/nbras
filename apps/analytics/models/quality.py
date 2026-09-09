import uuid

from django.conf import settings
from django.db import models


class QuestionQualityContribution(models.Model):
    """One replaceable analytics contribution per finalized AttemptQuestion.

    This ledger deliberately stores no question text, option text, answer text, phone,
    or email.  Stable option keys and frozen categorical metadata are sufficient for
    both student performance reads and global question-quality reconstruction.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt_question = models.OneToOneField(
        "attempts.AttemptQuestion",
        on_delete=models.CASCADE,
        related_name="quality_contribution",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="question_quality_contributions",
    )
    study_enrollment = models.ForeignKey(
        "curriculum.StudyEnrollment",
        on_delete=models.CASCADE,
        related_name="question_quality_contributions",
    )
    identity_key = models.CharField(max_length=180, db_index=True)
    question_version = models.ForeignKey(
        "question_bank.QuestionVersion",
        on_delete=models.PROTECT,
        related_name="quality_contributions",
    )
    ministerial_exam_item = models.ForeignKey(
        "ministerial_exams.MinisterialExamItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_contributions",
    )
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.PROTECT)
    unit = models.ForeignKey(
        "curriculum.Unit", on_delete=models.PROTECT, null=True, blank=True
    )
    lesson = models.ForeignKey(
        "curriculum.Lesson", on_delete=models.PROTECT, null=True, blank=True
    )
    source_type = models.CharField(max_length=30, db_index=True)
    difficulty = models.CharField(max_length=20, db_index=True)
    question_type = models.CharField(max_length=30, db_index=True)
    assessment_kind = models.CharField(max_length=30, blank=True, default="", db_index=True)
    attempt_type = models.CharField(max_length=30, db_index=True)
    is_remediation = models.BooleanField(default=False, db_index=True)
    outcome = models.CharField(max_length=20, db_index=True)
    was_answered = models.BooleanField(default=False)
    awarded_points = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    maximum_gradable_points = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    response_time_seconds = models.PositiveIntegerField(null=True, blank=True)
    selected_option_key = models.CharField(max_length=20, null=True, blank=True)
    option_keys_snapshot = models.JSONField(default=list, blank=True)
    correct_option_keys_snapshot = models.JSONField(default=list, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analytics_question_quality_contributions"
        indexes = [
            models.Index(
                fields=["user", "study_enrollment", "is_remediation", "subject"],
                name="an_qc_student_subject_idx",
            ),
            models.Index(
                fields=["user", "study_enrollment", "unit"],
                name="an_qc_student_unit_idx",
            ),
            models.Index(
                fields=["user", "study_enrollment", "lesson"],
                name="an_qc_student_lesson_idx",
            ),
        ]


class QuestionQualityAggregate(models.Model):
    """Global, non-PII quality read model for one exact historical identity."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity_key = models.CharField(max_length=180, unique=True)
    question_version = models.ForeignKey(
        "question_bank.QuestionVersion",
        on_delete=models.PROTECT,
        related_name="quality_aggregates",
    )
    ministerial_exam_item = models.ForeignKey(
        "ministerial_exams.MinisterialExamItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_aggregates",
    )
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.PROTECT)
    unit = models.ForeignKey(
        "curriculum.Unit", on_delete=models.PROTECT, null=True, blank=True
    )
    lesson = models.ForeignKey(
        "curriculum.Lesson", on_delete=models.PROTECT, null=True, blank=True
    )
    source_type = models.CharField(max_length=30, db_index=True)
    difficulty = models.CharField(max_length=20, db_index=True)
    question_type = models.CharField(max_length=30, db_index=True)
    presented_count = models.PositiveIntegerField(default=0)
    answered_count = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    incorrect_count = models.PositiveIntegerField(default=0)
    partial_count = models.PositiveIntegerField(default=0)
    unanswered_count = models.PositiveIntegerField(default=0)
    pending_count = models.PositiveIntegerField(default=0)
    earned_points = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    maximum_gradable_points = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    response_time_total_seconds = models.PositiveBigIntegerField(default=0)
    response_time_sample_count = models.PositiveIntegerField(default=0)
    option_distribution = models.JSONField(default=dict, blank=True)
    sample_size = models.PositiveIntegerField(default=0)
    sample_state = models.CharField(max_length=20, default="insufficient", db_index=True)
    quality_flags = models.JSONField(default=list, blank=True)
    first_finalized_at = models.DateTimeField(null=True, blank=True)
    last_finalized_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analytics_question_quality_aggregates"
        indexes = [
            models.Index(
                fields=["subject", "source_type", "sample_state"],
                name="an_qa_subject_sample_idx",
            ),
            models.Index(
                fields=["unit", "difficulty", "question_type"],
                name="an_qa_unit_meta_idx",
            ),
            models.Index(
                fields=["lesson", "sample_state"],
                name="an_qa_lesson_sample_idx",
            ),
        ]

    @property
    def correct_rate(self):
        graded = self.correct_count + self.incorrect_count + self.partial_count
        return self.correct_count / graded if graded else None

    @property
    def skip_rate(self):
        return self.unanswered_count / self.presented_count if self.presented_count else None

    @property
    def average_points_ratio(self):
        if not self.maximum_gradable_points:
            return None
        return float(self.earned_points / self.maximum_gradable_points)

    @property
    def average_response_time_seconds(self):
        if not self.response_time_sample_count:
            return None
        return round(self.response_time_total_seconds / self.response_time_sample_count, 2)
