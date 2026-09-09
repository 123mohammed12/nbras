import uuid
from django.db import models
from apps.curriculum.models.subject import ContentStatus


class ExamRole(models.TextChoices):
    FIRST = "first", "الدور الأول"
    SECOND = "second", "الدور الثاني"
    SUPPLEMENTARY = "supplementary", "تكميلي"
    OTHER = "other", "آخر"


class MinisterialExam(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_code = models.CharField(max_length=100, db_index=True)
    assessment = models.OneToOneField("assessments.Assessment", on_delete=models.SET_NULL, null=True, blank=True, related_name="ministerial_exam")
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.PROTECT, related_name="ministerial_exams")

    term = models.ForeignKey("curriculum.Term", on_delete=models.SET_NULL, null=True, blank=True, related_name="ministerial_exams")
    exam_year = models.PositiveIntegerField(db_index=True)
    exam_role = models.CharField(max_length=20, choices=ExamRole.choices, null=True, blank=True, db_index=True)
    model_number = models.CharField(max_length=50, default="1")
    free_access_rank = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    title = models.CharField(max_length=255)
    instructions = models.TextField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    total_points = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    total_questions = models.PositiveIntegerField(default=0)
    source_file_path = models.FileField(upload_to="ministerial_exams/", null=True, blank=True)
    source_checksum = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ministerial_exams"
        ordering = ["-exam_year", "model_number"]
        verbose_name = "النموذج الوزاري"
        verbose_name_plural = "النماذج الوزارية"
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "exam_year", "exam_role", "model_number"],
                name="unique_ministerial_exam_per_subject_year_role_model",
            ),
            models.UniqueConstraint(
                fields=["subject", "free_access_rank"],
                condition=models.Q(free_access_rank__isnull=False),
                name="unique_ministerial_free_rank_per_subject",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.exam_year})"


class MinisterialExamSection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ministerial_exam = models.ForeignKey(MinisterialExam, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=255, null=True, blank=True)
    instructions = models.TextField(null=True, blank=True)
    stimulus = models.ForeignKey("question_bank.QuestionStimulus", on_delete=models.SET_NULL, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ministerial_exam_sections"
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["ministerial_exam", "sort_order"],
                name="unique_exam_section_order",
            )
        ]


class MinisterialExamItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ministerial_exam = models.ForeignKey(MinisterialExam, on_delete=models.CASCADE, related_name="items")
    section = models.ForeignKey(MinisterialExamSection, on_delete=models.SET_NULL, null=True, blank=True, related_name="items")
    question_version = models.ForeignKey("question_bank.QuestionVersion", on_delete=models.PROTECT, related_name="ministerial_items")
    question_number = models.PositiveIntegerField()
    sort_order = models.PositiveIntegerField(default=0)
    points = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    official_options_order = models.JSONField(default=list, blank=True, help_text="[\"A\", \"B\", \"C\", \"D\"]")
    source_page = models.PositiveIntegerField(null=True, blank=True)
    source_image_path = models.ImageField(upload_to="ministerial_exams/items/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ministerial_exam_items"
        ordering = ["sort_order", "question_number"]
        verbose_name = "عنصر نموذج وزاري"
        verbose_name_plural = "عناصر النماذج الوزارية"
        constraints = [
            models.UniqueConstraint(
                fields=["ministerial_exam", "question_number"],
                name="unique_exam_question_number",
            ),
            models.UniqueConstraint(
                fields=["ministerial_exam", "sort_order"],
                name="unique_exam_item_order",
            ),
        ]


    def __str__(self):
        return f"{self.ministerial_exam.title} - Q{self.question_number}"


class LessonMinisterialBatch(models.Model):
    """Stable backend-owned identity for a mixed-year lesson test."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(
        "curriculum.Lesson",
        on_delete=models.PROTECT,
        related_name="ministerial_batches",
    )
    batch_index = models.PositiveIntegerField()
    target_size = models.PositiveIntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lesson_ministerial_batches"
        ordering = ["batch_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["lesson", "batch_index"],
                name="unique_lesson_ministerial_batch_index",
            )
        ]


class LessonMinisterialBatchItem(models.Model):
    batch = models.ForeignKey(
        LessonMinisterialBatch,
        on_delete=models.CASCADE,
        related_name="batch_items",
    )
    ministerial_exam_item = models.OneToOneField(
        MinisterialExamItem,
        on_delete=models.PROTECT,
        related_name="lesson_batch_item",
    )
    sort_order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lesson_ministerial_batch_items"
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "sort_order"],
                name="unique_lesson_ministerial_batch_item_order",
            )
        ]
