import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from apps.curriculum.models.subject import ContentStatus


class SourceType(models.TextChoices):
    MINISTERIAL = "ministerial", "وزاري"
    TRAINING = "training", "تدريبي"
    SELF_PRACTICE = "self_practice", "اختبر نفسك"
    CUSTOM = "custom", "مخصص"
    TEACHER_CREATED = "teacher_created", "إنشاء معلم"
    AI_GENERATED = "ai_generated", "ذكاء اصطناعي"


class QuestionType(models.TextChoices):
    MULTIPLE_CHOICE = "multiple_choice", "اختيار من متعدد"
    TRUE_FALSE = "true_false", "صواب / خطأ"
    MULTIPLE_SELECT = "multiple_select", "اختيارات متعددة"
    SHORT_ANSWER = "short_answer", "إجابة قصيرة"
    MATCHING = "matching", "مطابقة"
    ORDERING = "ordering", "ترتيب"
    NUMERIC = "numeric", "رقمي"
    ESSAY = "essay", "مقالي"
    INTERACTIVE = "interactive", "تفاعلي"


class DifficultyLevel(models.TextChoices):
    EASY = "easy", "سهل"
    MEDIUM = "medium", "متوسط"
    HARD = "hard", "صعب"


class PromptLayout(models.TextChoices):
    TEXT_ONLY = "text_only", "نص فقط"
    IMAGE_ONLY = "image_only", "صورة فقط"
    TEXT_THEN_IMAGE = "text_then_image", "نص ثم صورة"
    IMAGE_THEN_TEXT = "image_then_text", "صورة ثم نص"
    SIDE_BY_SIDE = "side_by_side", "جنباً إلى جنب"


class Question(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.PROTECT, related_name="questions")
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="questions")
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True, related_name="questions")
    topic = models.ForeignKey("curriculum.Topic", on_delete=models.SET_NULL, null=True, blank=True, related_name="questions")
    source_type = models.CharField(max_length=30, choices=SourceType.choices, default=SourceType.MINISTERIAL, db_index=True)
    question_type = models.CharField(max_length=30, choices=QuestionType.choices, default=QuestionType.MULTIPLE_CHOICE, db_index=True)
    difficulty = models.CharField(max_length=20, choices=DifficultyLevel.choices, default=DifficultyLevel.MEDIUM, db_index=True)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True)
    current_version = models.ForeignKey("QuestionVersion", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_questions")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_questions")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_questions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="published_questions",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="بيانات المنشأ والتتبع غير الوزارية؛ لا تُستخدم بدل العلاقات الأكاديمية.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "question_bank_questions"
        ordering = ["-created_at"]
        verbose_name = "السؤال"
        verbose_name_plural = "بنك الأسئلة"
        permissions = [
            ("review_question", "Can review question versions"),
            ("publish_question", "Can publish question versions"),
            ("retire_question", "Can retire questions"),
        ]
        indexes = [
            models.Index(
                fields=["subject", "status", "source_type", "difficulty", "question_type"],
                name="qb_q_pool_health_idx",
            ),
            models.Index(fields=["unit", "status", "source_type"], name="qb_q_unit_pool_idx"),
            models.Index(fields=["lesson", "status", "source_type"], name="qb_q_lesson_pool_idx"),
        ]

    def clean(self):
        from apps.question_bank.validators import validate_question_hierarchy
        validate_question_hierarchy(
            subject=self.subject,
            unit=self.unit,
            lesson=self.lesson,
            topic=self.topic,
        )
        if self.current_version and self.current_version.question_id != self.id:
            raise ValidationError("النسخة الحالية المحددة تنتمي لسؤال آخر.")

    def __str__(self):
        return f"Question {self.id} ({self.source_type})"

    def delete(self, *args, **kwargs):
        if self.versions.filter(published_at__isnull=False).exists():
            raise ValidationError("لا يمكن حذف سؤال له نسخة منشورة؛ استخدم التقاعد/الأرشفة.")
        return super().delete(*args, **kwargs)


class QuestionVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField(default=1)
    question_text = models.TextField(null=True, blank=True)
    prompt_layout = models.CharField(max_length=30, choices=PromptLayout.choices, default=PromptLayout.TEXT_ONLY)
    short_explanation = models.TextField(null=True, blank=True)
    explanation = models.TextField(null=True, blank=True)
    answer_key = models.JSONField(
        default=dict,
        blank=True,
        help_text="الإجابة المرجعية كما وردت من المصدر؛ لا تُعرض للطالب قبل التصحيح.",
    )
    points = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    status = models.CharField(
        max_length=20,
        choices=ContentStatus.choices,
        # Compatibility for legacy fixtures/internal importers. All supported
        # authoring entry points explicitly create Draft versions.
        default=ContentStatus.PUBLISHED,
        db_index=True,
    )
    is_current = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_question_versions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_question_versions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="published_question_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "question_bank_versions"
        ordering = ["-version_number"]
        verbose_name = "نسخة السؤال"
        verbose_name_plural = "نسخ الأسئلة"
        constraints = [
            models.UniqueConstraint(
                fields=["question", "version_number"],
                name="unique_question_version_number",
            ),
            models.UniqueConstraint(
                fields=["question"],
                condition=models.Q(is_current=True),
                name="unique_current_version_per_question",
            ),
        ]

    def __str__(self):
        return f"V{self.version_number} for {self.question_id}"

    @property
    def is_frozen(self):
        return self.published_at is not None

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            immutable_fields = (
                "question_id", "version_number", "question_text", "prompt_layout",
                "short_explanation", "explanation", "answer_key", "points",
            )
            if (
                original is not None
                and original.published_at is not None
                and any(getattr(original, field) != getattr(self, field) for field in immutable_fields)
            ):
                raise ValidationError("النسخة المنشورة غير قابلة للتعديل؛ أنشئ نسخة جديدة.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.published_at is not None:
            raise ValidationError("لا يمكن حذف نسخة منشورة محفوظة تاريخياً.")
        return super().delete(*args, **kwargs)


class QuestionAssetRole(models.TextChoices):
    QUESTION_STEM = "question_stem", "نص / صورة السؤال"
    SUPPORTING_DIAGRAM = "supporting_diagram", "رسم توضيحي"
    TABLE = "table", "جدول"
    EQUATION = "equation", "معادلة"
    EXPLANATION = "explanation", "الشرح والتوضيح"
    OTHER = "other", "آخر"


class QuestionAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_version = models.ForeignKey(QuestionVersion, on_delete=models.CASCADE, related_name="assets")
    asset_type = models.CharField(max_length=20, default="image")
    asset_role = models.CharField(max_length=30, choices=QuestionAssetRole.choices, default=QuestionAssetRole.QUESTION_STEM)
    file_path = models.FileField(upload_to="questions/")
    alt_text = models.CharField(max_length=255, null=True, blank=True)
    caption = models.CharField(max_length=255, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "question_bank_assets"
        ordering = ["sort_order", "created_at"]
        verbose_name = "ملحق السؤال"
        verbose_name_plural = "ملحقات وصور الأسئلة"
        constraints = [
            models.UniqueConstraint(
                fields=["question_version", "sort_order"],
                name="unique_question_asset_order",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.question_version.published_at is not None:
            raise ValidationError("لا يمكن تعديل ملحقات نسخة منشورة.")
        if not self.sort_order:
            max_order = QuestionAsset.objects.filter(question_version=self.question_version).aggregate(
                max_so=models.Max("sort_order")
            )["max_so"]
            self.sort_order = (max_order or 0) + 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.question_version.published_at is not None:
            raise ValidationError("لا يمكن حذف ملحق من نسخة منشورة.")
        return super().delete(*args, **kwargs)


class QuestionOption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_version = models.ForeignKey(QuestionVersion, on_delete=models.CASCADE, related_name="options")
    option_key = models.CharField(max_length=10, help_text="A, B, C, D")
    option_text = models.TextField(null=True, blank=True)
    option_image_path = models.ImageField(upload_to="question_options/", null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_correct = models.BooleanField(default=False)

    class Meta:
        db_table = "question_bank_options"
        ordering = ["sort_order", "option_key"]
        verbose_name = "خيار السؤال"
        verbose_name_plural = "خيارات السؤال"
        constraints = [
            models.UniqueConstraint(
                fields=["question_version", "option_key"],
                name="unique_option_key_per_question_version",
            ),
            models.UniqueConstraint(
                fields=["question_version", "sort_order"],
                name="unique_option_order_per_question_version",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.question_version.published_at is not None:
            raise ValidationError("لا يمكن تعديل خيارات نسخة منشورة.")
        if not self.sort_order:
            max_order = QuestionOption.objects.filter(question_version=self.question_version).aggregate(
                max_so=models.Max("sort_order")
            )["max_so"]
            self.sort_order = (max_order or 0) + 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.question_version.published_at is not None:
            raise ValidationError("لا يمكن حذف خيار من نسخة منشورة.")
        return super().delete(*args, **kwargs)



    def __str__(self):
        return f"{self.option_key}: {self.option_text or 'Image'}"


class StimulusType(models.TextChoices):
    READING_PASSAGE = "reading_passage", "قطعة قراءة"
    SHARED_IMAGE = "shared_image", "صورة مشتركة"
    FORMULA_SHEET = "formula_sheet", "قوانين وصيغ"
    INSTRUCTIONS = "instructions", "تعليمات"
    TABLE = "table", "جدول"
    DIAGRAM = "diagram", "رسم بياني"
    REFERENCE_TEXT = "reference_text", "نص مرجعي"
    OTHER = "other", "آخر"


class QuestionStimulus(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.PROTECT, related_name="stimuli")
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="stimuli")
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.SET_NULL, null=True, blank=True, related_name="stimuli")
    stimulus_type = models.CharField(max_length=30, choices=StimulusType.choices, default=StimulusType.READING_PASSAGE, db_index=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    text_content = models.TextField(null=True, blank=True)
    image_path = models.ImageField(upload_to="question_stimuli/", null=True, blank=True)
    file_path = models.FileField(upload_to="question_stimuli/files/", null=True, blank=True)
    layout = models.CharField(max_length=30, choices=PromptLayout.choices, default=PromptLayout.TEXT_ONLY)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "question_bank_stimuli"
        verbose_name = "المحتوى المشترك (Stimulus)"
        verbose_name_plural = "القطع والنصوص المشتركة"

    def __str__(self):
        return self.title or f"Stimulus {self.id}"


class QuestionStimulusLink(models.Model):
    stimulus = models.ForeignKey(QuestionStimulus, on_delete=models.CASCADE, related_name="links")
    question_version = models.ForeignKey(QuestionVersion, on_delete=models.CASCADE, related_name="stimulus_links")
    sort_order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "question_bank_stimulus_links"
        unique_together = ("stimulus", "question_version")
        ordering = ["sort_order"]

    def save(self, *args, **kwargs):
        if self.question_version.published_at is not None:
            raise ValidationError("لا يمكن تعديل محفزات نسخة منشورة.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.question_version.published_at is not None:
            raise ValidationError("لا يمكن حذف محفز من نسخة منشورة.")
        return super().delete(*args, **kwargs)


class QuestionPool(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pool_type = models.CharField(max_length=30, default="unit")
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.CASCADE)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.CASCADE, null=True, blank=True)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.CASCADE, null=True, blank=True)
    source_filter = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED)
    question_count = models.PositiveIntegerField(default=0)
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "question_bank_pools"


class QuestionPoolItem(models.Model):
    pool = models.ForeignKey(QuestionPool, on_delete=models.CASCADE, related_name="items")
    question_version = models.ForeignKey(QuestionVersion, on_delete=models.CASCADE)
    source_type = models.CharField(max_length=30, choices=SourceType.choices)
    difficulty = models.CharField(max_length=20, choices=DifficultyLevel.choices)
    sort_key = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "question_bank_pool_items"
        ordering = ["sort_key"]


class QuestionPoolStats(models.Model):
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.CASCADE)
    unit = models.ForeignKey("curriculum.Unit", on_delete=models.CASCADE, null=True, blank=True)
    lesson = models.ForeignKey("curriculum.Lesson", on_delete=models.CASCADE, null=True, blank=True)
    source_type = models.CharField(max_length=30, choices=SourceType.choices, null=True, blank=True)
    question_type = models.CharField(max_length=30, choices=QuestionType.choices, null=True, blank=True)
    difficulty = models.CharField(max_length=20, choices=DifficultyLevel.choices, null=True, blank=True)
    total_questions = models.PositiveIntegerField(default=0)
    published_questions = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "question_bank_pool_stats"
