import uuid
from django.db import models
from django.conf import settings


class AttemptType(models.TextChoices):
    NORMAL = "normal", "عادي"
    RETRY_FULL = "retry_full", "إعادة كاملة"
    WRONG_ANSWERS = "wrong_answers", "إعادة الخاطئة"
    UNANSWERED = "unanswered", "إعادة غير المجابة"
    REVIEW_FLAGGED = "review_flagged", "إعادة المؤشرة"


class AttemptStatus(models.TextChoices):
    CREATED = "created", "تم الإنشاء"
    IN_PROGRESS = "in_progress", "قيد التدريب"
    PAUSED = "paused", "مؤقت"
    SUBMITTED = "submitted", "مُسلّم"
    EVALUATED = "evaluated", "مُقيّم"
    PENDING_REVIEW = "pending_review", "قيد المراجعة اليدوية"
    EXPIRED = "expired", "منتهي"
    CANCELLED = "cancelled", "ملغى"


class AttemptMode(models.TextChoices):
    PRACTICE = "practice", "تدريب (فوري)"
    EXAM = "exam", "اختبار (نهائي)"


class AssessmentAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_attempt_id = models.UUIDField(null=True, blank=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assessment_attempts")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.PROTECT, related_name="assessment_attempts")
    # Static assessments keep their historical relationship.  Dynamic generated
    # attempts (custom tests now, reusable selection policies later) deliberately
    # have no synthetic Assessment/AssessmentVersion row.
    assessment = models.ForeignKey(
        "assessments.Assessment", on_delete=models.SET_NULL,
        related_name="attempts", null=True, blank=True,
    )
    assessment_version = models.ForeignKey("assessments.AssessmentVersion", on_delete=models.SET_NULL, null=True, blank=True)
    blueprint = models.ForeignKey("assessments.AssessmentBlueprint", on_delete=models.SET_NULL, null=True, blank=True)
    parent_attempt = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="child_attempts")
    attempt_type = models.CharField(max_length=30, choices=AttemptType.choices, default=AttemptType.NORMAL, db_index=True)
    mode = models.CharField(max_length=20, choices=AttemptMode.choices, default=AttemptMode.EXAM, db_index=True)
    status = models.CharField(max_length=20, choices=AttemptStatus.choices, default=AttemptStatus.CREATED, db_index=True)
    display_mode = models.CharField(max_length=20, default="single")
    contract_version = models.PositiveIntegerField(default=1)
    # Monotonic server-owned revision. Every effective answer mutation and the
    # finalization transition advances it; reads never do.
    revision = models.PositiveBigIntegerField(default=0)
    source_scope = models.JSONField(default=dict, blank=True)
    dynamic_assessment_type = models.CharField(max_length=30, blank=True, default="", db_index=True)
    dynamic_title = models.CharField(max_length=255, blank=True, default="")
    dynamic_subject = models.ForeignKey(
        "curriculum.Subject", on_delete=models.PROTECT, null=True, blank=True,
        related_name="dynamic_assessment_attempts",
    )
    selection_spec_snapshot = models.JSONField(default=dict, blank=True)
    selection_policy_snapshot = models.JSONField(default=dict, blank=True)
    feedback_policy = models.CharField(max_length=20, default="deferred")
    timing_mode = models.CharField(max_length=20, default="none")
    questions_shuffled = models.BooleanField(default=False)
    options_shuffled = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    current_question_id = models.UUIDField(null=True, blank=True)
    answered_count = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    incorrect_count = models.PositiveIntegerField(default=0)
    unanswered_count = models.PositiveIntegerField(default=0)
    pending_review_count = models.PositiveIntegerField(default=0)
    score = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    maximum_score = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    official_maximum_score = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    duration_seconds = models.PositiveIntegerField(default=0)
    submission_reason = models.CharField(max_length=30, default="manual")
    frozen_at = models.DateTimeField(null=True, blank=True)
    auto_submit_on_expiry = models.BooleanField(default=True)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    device_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assessment_attempts"
        ordering = ["-created_at"]
        verbose_name = "محاولة اختبار"
        verbose_name_plural = "محاولات الاختبارات"

    def __str__(self):
        return f"Attempt {self.id} - {self.user} ({self.status})"

    @property
    def assessment_title(self):
        return self.dynamic_title or (self.assessment.title if self.assessment_id else "")

    @property
    def assessment_kind(self):
        return self.dynamic_assessment_type or (
            self.assessment.assessment_type if self.assessment_id else ""
        )


class AttemptQuestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name="attempt_questions")
    question_version = models.ForeignKey("question_bank.QuestionVersion", on_delete=models.PROTECT)
    assessment_item = models.ForeignKey("assessments.AssessmentItem", on_delete=models.SET_NULL, null=True, blank=True)
    ministerial_exam_item = models.ForeignKey(
        "ministerial_exams.MinisterialExamItem", on_delete=models.PROTECT,
        null=True, blank=True, related_name="attempt_questions",
    )
    source_type = models.CharField(max_length=30, default="ministerial")
    sort_order = models.PositiveIntegerField(default=0)
    points = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    is_reference = models.BooleanField(default=False)
    options_order_snapshot = models.JSONField(default=list, blank=True)
    source_metadata_snapshot = models.JSONField(default=dict, blank=True)
    question_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attempt_questions"
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "sort_order"],
                name="unique_attempt_question_order",
            )
        ]

    def __str__(self):
        return f"{self.attempt_id} - Q{self.sort_order}"


class AttemptStimulus(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name="attempt_stimuli")
    source_stimulus = models.ForeignKey("question_bank.QuestionStimulus", on_delete=models.SET_NULL, null=True, blank=True)
    stimulus_type = models.CharField(max_length=30, default="reading_passage")
    title = models.CharField(max_length=255, null=True, blank=True)
    text_content = models.TextField(null=True, blank=True)
    image_path_snapshot = models.CharField(max_length=500, null=True, blank=True)
    file_path_snapshot = models.CharField(max_length=500, null=True, blank=True)
    layout = models.CharField(max_length=30, default="text_only")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attempt_stimuli"
        ordering = ["sort_order"]


class AttemptQuestionStimulus(models.Model):
    attempt_question = models.ForeignKey(AttemptQuestion, on_delete=models.CASCADE, related_name="stimulus_links")
    attempt_stimulus = models.ForeignKey(AttemptStimulus, on_delete=models.CASCADE, related_name="question_links")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attempt_question_stimuli"
        ordering = ["sort_order"]


class AttemptAnswer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name="answers")
    attempt_question = models.ForeignKey(AttemptQuestion, on_delete=models.CASCADE, related_name="answers")
    selected_option_id = models.UUIDField(null=True, blank=True)
    selected_option_key = models.CharField(max_length=20, null=True, blank=True)
    answer_text = models.TextField(null=True, blank=True)
    answer_payload = models.JSONField(default=dict, blank=True)
    is_flagged = models.BooleanField(default=False)
    is_visited = models.BooleanField(default=False)
    is_evaluated = models.BooleanField(default=False)
    client_revision = models.PositiveIntegerField(default=0)
    server_revision = models.PositiveIntegerField(default=0)
    is_correct = models.BooleanField(null=True, blank=True)
    awarded_points = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    answered_at = models.DateTimeField(auto_now_add=True)
    client_updated_at = models.DateTimeField(null=True, blank=True)
    server_updated_at = models.DateTimeField(auto_now=True)
    response_time_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "attempt_answers"
        verbose_name = "إجابة المحاولة"
        verbose_name_plural = "إجابات المحاولات"
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "attempt_question"],
                name="unique_answer_per_attempt_question",
            )
        ]



class AttemptAnalysis(models.Model):
    attempt = models.OneToOneField(AssessmentAttempt, on_delete=models.CASCADE, related_name="analysis")
    unit_breakdown = models.JSONField(default=dict, blank=True)
    lesson_breakdown = models.JSONField(default=dict, blank=True)
    difficulty_breakdown = models.JSONField(default=dict, blank=True)
    year_breakdown = models.JSONField(default=dict, blank=True)
    source_breakdown = models.JSONField(default=dict, blank=True)
    strengths = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=1)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attempt_analyses"


class QuestionPerformanceEvidence(models.Model):
    """Incremental, rebuildable per-user evidence for one exact question identity.

    Ministerial identities are occurrences; other sources use the stable logical
    Question identity.  Historical rendering always comes from the referenced
    AttemptQuestion snapshot, never from the current QuestionVersion.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="question_performance_evidence",
    )
    study_enrollment = models.ForeignKey(
        "curriculum.StudyEnrollment", on_delete=models.CASCADE,
        related_name="question_performance_evidence",
    )
    identity_key = models.CharField(max_length=100)
    source_type = models.CharField(max_length=30, db_index=True)
    question = models.ForeignKey(
        "question_bank.Question", on_delete=models.PROTECT,
        related_name="performance_evidence",
    )
    question_version = models.ForeignKey(
        "question_bank.QuestionVersion", on_delete=models.PROTECT,
        related_name="performance_evidence",
    )
    ministerial_exam_item = models.ForeignKey(
        "ministerial_exams.MinisterialExamItem", on_delete=models.PROTECT,
        null=True, blank=True, related_name="performance_evidence",
    )
    subject = models.ForeignKey(
        "curriculum.Subject", on_delete=models.PROTECT,
        related_name="question_performance_evidence",
    )
    unit = models.ForeignKey(
        "curriculum.Unit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="question_performance_evidence",
    )
    lesson = models.ForeignKey(
        "curriculum.Lesson", on_delete=models.PROTECT, null=True, blank=True,
        related_name="question_performance_evidence",
    )
    difficulty = models.CharField(max_length=20, db_index=True)
    question_type = models.CharField(max_length=30, db_index=True)
    wrong_count = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    correct_after_wrong_count = models.PositiveIntegerField(default=0)
    last_outcome = models.CharField(max_length=20, blank=True, default="")
    last_awarded_points = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    last_maximum_points = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    last_attempt_question = models.ForeignKey(
        AttemptQuestion, on_delete=models.PROTECT,
        related_name="latest_performance_evidence",
    )
    last_wrong_attempt_question = models.ForeignKey(
        AttemptQuestion, on_delete=models.PROTECT, null=True, blank=True,
        related_name="latest_wrong_evidence",
    )
    last_seen_at = models.DateTimeField()
    last_wrong_at = models.DateTimeField(null=True, blank=True)
    last_practiced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "attempt_question_performance_evidence"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "study_enrollment", "identity_key"],
                name="unique_question_performance_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "study_enrollment", "subject", "wrong_count"], name="att_ev_wrong_scope_idx"),
            models.Index(fields=["user", "study_enrollment", "lesson", "difficulty"], name="att_ev_weak_scope_idx"),
        ]


class QuestionPerformanceEvent(models.Model):
    """Idempotency ledger for incrementally projecting finalized answers."""

    attempt_question = models.OneToOneField(
        AttemptQuestion, on_delete=models.CASCADE,
        related_name="performance_event",
    )
    evidence = models.ForeignKey(
        QuestionPerformanceEvidence, on_delete=models.CASCADE,
        related_name="events",
    )
    outcome = models.CharField(max_length=20)
    awarded_points = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    maximum_points = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attempt_question_performance_events"
