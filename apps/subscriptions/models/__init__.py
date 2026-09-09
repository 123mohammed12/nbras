import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "نشط"
    EXPIRED = "expired", "منتهي"
    CANCELLED = "cancelled", "ملغى"
    REVOKED = "revoked", "مسحوب"


class ActivationCodeStatus(models.TextChoices):
    AVAILABLE = "available", "متاح"
    REDEEMED = "redeemed", "مستخدم"
    EXPIRED = "expired", "منتهي"
    REVOKED = "revoked", "ملغى"
    ACTIVE = "active", "متاح (قديم)"
    EXHAUSTED = "exhausted", "مستخدم (قديم)"
    DISABLED = "disabled", "ملغى (قديم)"


class ActivationCodeHashVersion(models.TextChoices):
    LEGACY_SHA256 = "legacy_sha256", "SHA-256 (قديم)"
    HMAC_SHA256_V1 = "hmac_sha256_v1", "HMAC-SHA256 (v1)"


class PackageTierType(models.TextChoices):
    SUBJECT_COUNT = "subject_count", "عدد مواد"
    ALL_SUBJECTS = "all_subjects", "جميع المواد"


class SubscriptionSource(models.TextChoices):
    CODE = "code", "رمز تفعيل"
    ADMIN = "admin", "إدارة"
    DISTRIBUTOR = "distributor", "موزع"
    LEGACY_GUEST = "legacy_guest", "اشتراك زائر قديم"
    GOOGLE_PLAY = "google_play", "Google Play (مستقبلي)"
    YEMENI_WALLET = "yemeni_wallet", "محفظة يمنية (مستقبلي)"
    OTHER_PAYMENT = "other_payment", "دفع آخر (مستقبلي)"


class GenerationMode(models.TextChoices):
    CUSTOM = "custom", "مخصص"
    MOCK = "mock", "محاكاة"


class SubscriptionPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    academic_year = models.ForeignKey("curriculum.AcademicYear", on_delete=models.PROTECT, null=True, blank=True, related_name="subscription_plans")
    grade = models.ForeignKey("curriculum.Grade", on_delete=models.PROTECT, null=True, blank=True, related_name="subscription_plans")
    section = models.ForeignKey("curriculum.Section", on_delete=models.PROTECT, null=True, blank=True, related_name="subscription_plans")
    tier_type = models.CharField(max_length=20, choices=PackageTierType.choices, default=PackageTierType.SUBJECT_COUNT, db_index=True)
    subject_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_days = models.PositiveIntegerField(default=365)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    offer_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    offer_starts_at = models.DateTimeField(null=True, blank=True)
    offer_ends_at = models.DateTimeField(null=True, blank=True)
    currency = models.CharField(max_length=10, default="YER")
    is_active = models.BooleanField(default=True, db_index=True)
    is_catalog_visible = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions_plans"
        ordering = ["sort_order", "subject_limit", "code"]
        verbose_name = "خطة الاشتراك"
        verbose_name_plural = "خطط الاشتراكات"

    def clean(self):
        super().clean()
        if self.duration_days <= 0:
            raise ValidationError("مدة الخطة يجب أن تكون أكبر من صفر.")
        if self.price < 0:
            raise ValidationError("سعر الخطة لا يمكن أن يكون سالباً.")
        if self.tier_type == PackageTierType.SUBJECT_COUNT and self.academic_year_id and not self.subject_limit:
            raise ValidationError("باقة عدد المواد تتطلب حداً موجباً للمواد.")
        if self.tier_type == PackageTierType.ALL_SUBJECTS and self.subject_limit is not None:
            raise ValidationError("باقة جميع المواد لا تستخدم حداً ثابتاً للمواد.")
        if self.offer_price is not None and (self.offer_price < 0 or self.offer_price >= self.price):
            raise ValidationError("سعر العرض يجب أن يكون غير سالب وأقل من السعر العادي.")
        if self.section_id and self.grade_id and self.section.grade_id != self.grade_id:
            raise ValidationError("المسار لا ينتمي إلى الصف المحدد.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def current_display_price(self, at=None):
        at = at or timezone.now()
        if self.offer_price is not None and (self.offer_starts_at is None or self.offer_starts_at <= at) and (self.offer_ends_at is None or self.offer_ends_at > at):
            return self.offer_price
        return self.price

    def is_immutable(self):
        return self.user_subscriptions.exists() or ActivationCodeUsage.objects.filter(activation_code__plan=self).exists()

    def __str__(self):
        return self.name


class ActivationCodeBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_code = models.CharField(max_length=60, unique=True, db_index=True)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="code_batches")
    quantity = models.PositiveIntegerField()
    code_expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_activation_code_batches"
        ordering = ["-created_at"]
        verbose_name = "دفعة رموز التفعيل"
        verbose_name_plural = "دفعات رموز التفعيل"
        permissions = [
            ("generate_code_batch", "Can generate activation code batches"),
        ]

    def __str__(self):
        return self.batch_code


class ActivationCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_hash = models.CharField(max_length=64, unique=True, db_index=True)
    hash_version = models.CharField(max_length=30, choices=ActivationCodeHashVersion.choices, default=ActivationCodeHashVersion.HMAC_SHA256_V1, db_index=True)
    display_code_masked = models.CharField(max_length=50)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name="activation_codes")
    batch = models.ForeignKey(ActivationCodeBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="codes")
    max_uses = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ActivationCodeStatus.choices, default=ActivationCodeStatus.AVAILABLE, db_index=True)
    batch_code = models.CharField(max_length=50, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions_activation_codes"
        verbose_name = "رمز التفعيل"
        verbose_name_plural = "رموز التفعيل"

    def clean(self):
        super().clean()
        if self.max_uses != 1:
            raise ValidationError("رموز FE-08 أحادية الاستخدام.")
        if self.used_count > 1:
            raise ValidationError("رمز التفعيل لا يمكن استخدامه أكثر من مرة.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_code_masked


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE, related_name="subscriptions")
    academic_year = models.ForeignKey("curriculum.AcademicYear", on_delete=models.PROTECT, null=True, blank=True, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="user_subscriptions")
    selected_subjects = models.ManyToManyField("curriculum.Subject", blank=True, related_name="selected_subscriptions")
    is_all_subjects = models.BooleanField(default=False, db_index=True)
    status = models.CharField(max_length=20, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE, db_index=True)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    activation_code_usage = models.ForeignKey("ActivationCodeUsage", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    source = models.CharField(max_length=50, choices=SubscriptionSource.choices, default=SubscriptionSource.CODE)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="activated_subscriptions")
    commercial_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions_user_subscriptions"
        verbose_name = "اشتراك الطالب"
        verbose_name_plural = "اشتراكات الطلاب"
        indexes = [models.Index(fields=["user", "academic_year", "status"], name="sub_user_year_status_idx")]
        permissions = [
            ("direct_activate_subscription", "Can directly activate student subscriptions"),
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValidationError("تاريخ الانتهاء يجب أن يكون بعد تاريخ البداية.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} - {self.plan.name}"


class ActivationCodeUsage(models.Model):
    activation_code = models.ForeignKey(ActivationCode, on_delete=models.CASCADE, related_name="usages")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    study_enrollment = models.ForeignKey("curriculum.StudyEnrollment", on_delete=models.CASCADE)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, null=True, blank=True)
    used_at = models.DateTimeField(auto_now_add=True)
    request_id = models.CharField(max_length=100, null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "subscriptions_code_usages"
        verbose_name = "استخدام رمز التفعيل"
        verbose_name_plural = "استخدامات رموز التفعيل"
        constraints = [
            models.UniqueConstraint(fields=["activation_code"], name="unique_single_activation_code_usage"),
            models.UniqueConstraint(fields=["user", "idempotency_key"], condition=models.Q(idempotency_key__isnull=False), name="unique_activation_redemption_idempotency_per_user"),
        ]

    def __str__(self):
        return f"{self.user} used {self.activation_code.display_code_masked}"


class SubscriptionAudit(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="audit_events")
    action = models.CharField(max_length=40)
    source = models.CharField(max_length=50, choices=SubscriptionSource.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    before_state = models.JSONField(default=dict, blank=True)
    after_state = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_audit"
        ordering = ["-created_at"]


class GeneratedQuestionUse(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="generated_question_uses")
    academic_year = models.ForeignKey("curriculum.AcademicYear", on_delete=models.PROTECT, null=True, blank=True)
    question = models.ForeignKey("question_bank.Question", on_delete=models.PROTECT, related_name="generation_uses")
    mode = models.CharField(max_length=20, choices=GenerationMode.choices)
    attempt = models.ForeignKey("attempts.AssessmentAttempt", on_delete=models.CASCADE, related_name="generation_uses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_generated_question_uses"
        constraints = [models.UniqueConstraint(fields=["user", "academic_year", "question", "mode"], name="unique_generated_question_use")]
        indexes = [models.Index(fields=["user", "academic_year", "mode", "question"], name="gen_use_pool_idx")]


class FreeGenerationUse(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="free_generation_uses")
    academic_year = models.ForeignKey("curriculum.AcademicYear", on_delete=models.PROTECT, null=True, blank=True)
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.PROTECT)
    mode = models.CharField(max_length=20, choices=GenerationMode.choices)
    attempt = models.OneToOneField("attempts.AssessmentAttempt", on_delete=models.PROTECT, related_name="free_generation_use")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_free_generation_uses"
        indexes = [models.Index(fields=["user", "academic_year", "subject", "mode"], name="free_gen_use_idx")]
