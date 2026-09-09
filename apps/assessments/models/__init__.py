import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from apps.curriculum.models.subject import ContentStatus


class AssessmentType(models.TextChoices):
    MINISTERIAL_EXAM = "ministerial_exam", "نموذج وزاري كامل"
    LESSON_TEST = "lesson_test", "اختبار درس"
    UNIT_TEST = "unit_test", "اختبار وحدة"
    SUBJECT_TEST = "subject_test", "اختبار مادة (محدود)"
    SELF_PRACTICE = "self_practice", "اختبر نفسك"
    CUSTOM_TEST = "custom_test", "اختبار مخصص"
    MOCK_EXAM = "mock_exam", "اختبار محاكاة"
    TRAINING_TEST = "training_test", "اختبار تدريبي"
    WRONG_ANSWERS_TEST = "wrong_answers_test", "إعادة الأسئلة الخاطئة"
    UNANSWERED_TEST = "unanswered_test", "إعادة الأسئلة غير المجابة"
    MONTHLY_TEST = "monthly_test", "اختبار شهري"
    GROUP_TEST = "group_test", "اختبار مجموعات"
    AI_GENERATED_TEST = "ai_generated_test", "اختبار مصنع بالذكاء الاصطناعي"


    LESSON_MINISTERIAL = "lesson_ministerial", "Lesson ministerial practice"


class ShufflePolicy(models.TextChoices):
    NEVER = "never", "أبداً"
    ALWAYS = "always", "دائماً"
    USER_CHOICE = "user_choice", "خيار المستخدم"


class FeedbackPolicy(models.TextChoices):
    IMMEDIATE = "immediate", "Immediate"
    DEFERRED = "deferred", "Deferred"


class TimingMode(models.TextChoices):
    NONE = "none", "No timer"
    FIXED = "fixed", "Fixed duration"
    CALCULATED = "calculated", "Calculated per question"


class Assessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    assessment_type = models.CharField(max_length=30, choices=AssessmentType.choices, default=AssessmentType.LESSON_TEST, db_index=True)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.PROTECT, related_name="assessments")
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="assessments")
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True, related_name="assessments")
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assessments"
        ordering = ["-created_at"]
        verbose_name = "الاختبار"
        verbose_name_plural = "الاختبارات"

    def __str__(self):
        return f"{self.title} ({self.assessment_type})"


class AssessmentVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField(default=1)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    total_points = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    question_count = models.PositiveIntegerField(default=0)
    passing_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=50.00)
    allow_resume = models.BooleanField(default=True)
    allow_answer_change = models.BooleanField(default=True)
    allow_previous_question = models.BooleanField(default=True)
    allowed_display_modes = models.JSONField(default=list, blank=True, help_text="[\"single\", \"full\"]")
    default_display_mode = models.CharField(max_length=20, default="single")
    allowed_attempt_modes = models.JSONField(default=list, blank=True, help_text="[\"practice\", \"exam\"]")
    question_shuffle_policy = models.CharField(max_length=20, choices=ShufflePolicy.choices, default=ShufflePolicy.ALWAYS)
    option_shuffle_policy = models.CharField(max_length=20, choices=ShufflePolicy.choices, default=ShufflePolicy.ALWAYS)
    explanation_policy = models.CharField(max_length=30, default="after_submit")
    feedback_policy = models.CharField(
        max_length=20,
        choices=FeedbackPolicy.choices,
        default=FeedbackPolicy.IMMEDIATE,
    )
    timing_mode = models.CharField(
        max_length=20,
        choices=TimingMode.choices,
        default=TimingMode.NONE,
    )
    seconds_per_question = models.PositiveIntegerField(null=True, blank=True)
    is_current = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_versions"
        ordering = ["-version_number"]
        verbose_name = "نسخة الاختبار"
        verbose_name_plural = "نسخ الاختبارات"
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "version_number"],
                name="unique_assessment_version_number",
            ),
            models.UniqueConstraint(
                fields=["assessment"],
                condition=models.Q(is_current=True),
                name="unique_current_assessment_version",
            ),
        ]


class AssessmentItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment_version = models.ForeignKey(AssessmentVersion, on_delete=models.CASCADE, related_name="items")
    question_version = models.ForeignKey("question_bank.QuestionVersion", on_delete=models.PROTECT)
    ministerial_exam_item = models.ForeignKey("ministerial_exams.MinisterialExamItem", on_delete=models.SET_NULL, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    points = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    official_options_order = models.JSONField(default=list, blank=True)
    required = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_items"
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment_version", "sort_order"],
                name="unique_assessment_item_order",
            ),
            models.UniqueConstraint(
                fields=["assessment_version", "question_version"],
                name="unique_question_per_assessment_version",
            ),
        ]



class AssessmentBlueprint(models.Model):
    """Stable identity for a reusable generated-assessment policy.

    The original pre-AR-05 fields remain for backwards compatibility.  New
    generated products store immutable policy revisions in ``versions``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=120, unique=True, null=True, blank=True)
    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=ContentStatus.choices,
        default=ContentStatus.DRAFT, db_index=True,
    )
    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="blueprints",
        null=True, blank=True,
    )
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.CASCADE)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True)
    pool = models.ForeignKey("question_bank.QuestionPool", on_delete=models.SET_NULL, null=True, blank=True)
    source_types = models.JSONField(default=list, blank=True)
    years = models.JSONField(default=list, blank=True)
    difficulties = models.JSONField(default=list, blank=True)
    question_types = models.JSONField(default=list, blank=True)
    question_count = models.PositiveIntegerField(default=10)
    unit_distribution = models.JSONField(null=True, blank=True)
    ministerial_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    training_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exclude_previously_answered = models.BooleanField(default=False)
    max_questions_limit = models.PositiveIntegerField(default=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assessment_blueprints"

    def __str__(self):
        return self.title or self.key or str(self.id)


class AssessmentBlueprintVersion(models.Model):
    """Immutable, historically reproducible Mock policy revision."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blueprint = models.ForeignKey(
        AssessmentBlueprint, on_delete=models.CASCADE, related_name="versions",
    )
    version_number = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=ContentStatus.choices,
        default=ContentStatus.DRAFT, db_index=True,
    )
    question_count = models.PositiveIntegerField()
    duration_minutes = models.PositiveIntegerField()
    total_points = models.DecimalField(max_digits=6, decimal_places=2)
    source_types = models.JSONField(default=list)
    years = models.JSONField(default=list, blank=True)
    scope = models.JSONField(default=dict)
    unit_distribution = models.JSONField(default=dict)
    difficulty_distribution = models.JSONField(default=dict)
    question_type_distribution = models.JSONField(default=dict)
    # Joint buckets are authoritative.  Marginal distributions above are
    # presentation/audit summaries and are checked against these buckets.
    selection_buckets = models.JSONField(default=list)
    selection_policy_version = models.PositiveIntegerField(default=2)
    is_current = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_blueprint_versions"
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["blueprint", "version_number"],
                name="unique_blueprint_version_number",
            ),
            models.UniqueConstraint(
                fields=["blueprint"], condition=models.Q(is_current=True),
                name="unique_current_blueprint_version",
            ),
        ]

    def __str__(self):
        return f"{self.blueprint} v{self.version_number}"

    def save(self, *args, **kwargs):
        original = None
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            immutable = (
                "blueprint_id", "version_number", "title", "question_count",
                "duration_minutes", "total_points", "source_types", "years",
                "scope", "unit_distribution", "difficulty_distribution",
                "question_type_distribution", "selection_buckets",
                "selection_policy_version",
            )
            if (
                original is not None
                and original.status == ContentStatus.PUBLISHED
                and any(getattr(original, field) != getattr(self, field) for field in immutable)
            ):
                raise ValidationError(
                    "Published blueprint versions are immutable; create a new version."
                )
        if (
            self.status == ContentStatus.PUBLISHED
            and (original is None or original.status != ContentStatus.PUBLISHED)
        ):
            from apps.attempts.services.mock_exams import blueprint_pool_readiness

            readiness = blueprint_pool_readiness(self)
            if not readiness["ready"]:
                raise ValidationError({"status": [
                    f"Mock blueprint is not ready: {readiness}"
                ]})
        super().save(*args, **kwargs)


class TrainingBatchScope(models.TextChoices):
    LESSON = "lesson", "درس"
    UNIT = "unit", "وحدة"
    SUBJECT = "subject", "مادة"


class TrainingBatch(models.Model):
    """Stable, append-only identity for a non-ministerial Training set."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope_type = models.CharField(max_length=20, choices=TrainingBatchScope.choices)
    scope_key = models.CharField(max_length=255, db_index=True)
    subject = models.ForeignKey(
        "curriculum.Subject", on_delete=models.PROTECT, related_name="training_batches"
    )
    unit = models.ForeignKey(
        "curriculum.Unit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="training_batches",
    )
    lesson = models.ForeignKey(
        "curriculum.Lesson", on_delete=models.PROTECT, null=True, blank=True,
        related_name="training_batches",
    )
    batch_index = models.PositiveIntegerField()
    free_access_rank = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    target_size = models.PositiveIntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_training_batches"
        ordering = ["batch_index", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["scope_key", "batch_index"],
                name="unique_training_batch_scope_index",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type=TrainingBatchScope.LESSON, unit__isnull=False, lesson__isnull=False)
                    | models.Q(scope_type=TrainingBatchScope.UNIT, unit__isnull=False, lesson__isnull=True)
                    | models.Q(scope_type=TrainingBatchScope.SUBJECT, unit__isnull=True, lesson__isnull=True)
                ),
                name="valid_training_batch_scope",
            ),
            models.UniqueConstraint(
                fields=["scope_key", "free_access_rank"],
                condition=models.Q(free_access_rank__isnull=False),
                name="unique_training_free_rank_per_scope",
            ),
        ]


class TrainingBatchItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        TrainingBatch, on_delete=models.CASCADE, related_name="items"
    )
    question_version = models.ForeignKey(
        "question_bank.QuestionVersion", on_delete=models.PROTECT,
        related_name="training_batch_items",
    )
    sort_order = models.PositiveIntegerField()
    source_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_training_batch_items"
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "sort_order"],
                name="unique_training_batch_item_order",
            ),
            models.UniqueConstraint(
                fields=["batch", "question_version"],
                name="unique_training_question_per_batch",
            ),
        ]
