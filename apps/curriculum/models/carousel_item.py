import uuid
from django.db import models
from django.utils import timezone


class CarouselItemType(models.TextChoices):
    OFFER = "offer", "عرض"
    PACKAGE = "package", "باقة"
    NEW_FEATURE = "new_feature", "ميزة جديدة"
    UPDATE = "update", "تحديث"
    ANNOUNCEMENT = "announcement", "إعلان"


class CarouselCtaType(models.TextChoices):
    NONE = "none", "بدون إجراء"
    SUBSCRIPTION_CATALOG = "subscription_catalog", "دليل الاشتراكات"
    SUBJECT = "subject", "المادة"
    UNIT = "unit", "الوحدة"
    LESSON = "lesson", "الدرس"
    DOWNLOADS = "downloads", "التحميلات"
    PROGRESS = "progress", "التقدم"
    SETTINGS = "settings", "الإعدادات"


class DashboardBanner(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item_type = models.CharField(
        max_length=30,
        choices=CarouselItemType.choices,
        default=CarouselItemType.ANNOUNCEMENT,
        db_index=True,
    )
    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True, default="")
    image_path = models.FileField(
        upload_to="curriculum/banners/",
        null=True,
        blank=True,
    )
    badge_text = models.CharField(max_length=50, blank=True, default="")
    cta_label = models.CharField(max_length=100, blank=True, default="")
    cta_type = models.CharField(
        max_length=30,
        choices=CarouselCtaType.choices,
        default=CarouselCtaType.NONE,
    )
    target_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="معرف الهدف للربط الآمن (مثل معرف المادة أو الوحدة)",
    )
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    # Optional academic targeting
    academic_year = models.ForeignKey(
        "curriculum.AcademicYear",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="dashboard_banners",
    )
    grade = models.ForeignKey(
        "curriculum.Grade",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="dashboard_banners",
    )
    section = models.ForeignKey(
        "curriculum.Section",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="dashboard_banners",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "curriculum_dashboard_banners"
        ordering = ["sort_order", "-created_at"]
        verbose_name = "بانر الشاشة الرئيسية"
        verbose_name_plural = "بانرات الشاشة الرئيسية"

    def is_currently_visible(self, at=None):
        at = at or timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > at:
            return False
        if self.ends_at and self.ends_at <= at:
            return False
        return True

    def __str__(self):
        return f"[{self.get_item_type_display()}] {self.title}"
