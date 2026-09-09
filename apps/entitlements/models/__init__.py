import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


class ScopeType(models.TextChoices):
    PLATFORM = "platform", "منصة كاملة"
    GRADE = "grade", "صف دراسي كامل"
    SECTION = "section", "قسم دراسي كامل"
    SUBJECT = "subject", "مادة دراسية"
    UNIT = "unit", "وحدة دراسية"
    ASSESSMENT = "assessment", "اختبار مخصص"


class EntitlementType(models.TextChoices):
    FULL_ACCESS = "full_access", "وصول كامل"
    SUBJECT_ACCESS = "subject_access", "وصول لمادة"
    UNIT_ACCESS = "unit_access", "وصول لوحدة"
    ASSESSMENT_ACCESS = "assessment_access", "وصول لاختبار"


class Entitlement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    entitlement_type = models.CharField(
        max_length=50,
        choices=EntitlementType.choices,
        default=EntitlementType.SUBJECT_ACCESS,
    )
    scope_type = models.CharField(
        max_length=50,
        choices=ScopeType.choices,
        default=ScopeType.SUBJECT,
        db_index=True,
    )
    grade = models.ForeignKey(
        "curriculum.Grade",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlements",
    )
    section = models.ForeignKey(
        "curriculum.Section",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlements",
    )
    subject = models.ForeignKey(
        "curriculum.Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlements",
    )
    unit = models.ForeignKey(
        "curriculum.Unit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlements",
    )
    assessment = models.ForeignKey(
        "assessments.Assessment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlements",
    )
    limits = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "entitlements"
        verbose_name = "الاستحقاق"
        verbose_name_plural = "الاستحقاقات"

    def clean(self):
        super().clean()
        if self.scope_type == ScopeType.PLATFORM:
            if any([self.grade, self.section, self.subject, self.unit, self.assessment]):
                raise ValidationError("استحقاق المنصة العامة يجب ألا يحدد أي هدف أكاديمي فرعي.")

        elif self.scope_type == ScopeType.GRADE:
            if not self.grade:
                raise ValidationError("استحقاق الصف يتطلب تحديد Grade.")
            if any([self.section, self.subject, self.unit, self.assessment]):
                raise ValidationError("استحقاق الصف يجب ألا يحدد قسم أو مادة أو وحدة أو اختبار.")

        elif self.scope_type == ScopeType.SECTION:
            if not self.grade or not self.section:
                raise ValidationError("استحقاق القسم يتطلب تحديد Grade و Section.")
            if self.section.grade_id != self.grade_id:
                raise ValidationError("الـ Section المحدد لا ينتمي للـ Grade المحددة.")
            if any([self.subject, self.unit, self.assessment]):
                raise ValidationError("استحقاق القسم يجب ألا يحدد مادة أو وحدة أو اختبار.")

        elif self.scope_type == ScopeType.SUBJECT:
            if not self.subject:
                raise ValidationError("استحقاق المادة يتطلب تحديد Subject.")
            if self.grade and self.subject.grade_id != self.grade_id:
                raise ValidationError("المادة لا تنتمي للصف المحدد.")
            if self.section and self.subject.section_id != self.section_id:
                raise ValidationError("المادة لا تنتمي للقسم المحدد.")
            if any([self.unit, self.assessment]):
                raise ValidationError("استحقاق المادة يجب ألا يحدد وحدة أو اختبار.")

        elif self.scope_type == ScopeType.UNIT:
            if not self.unit:
                raise ValidationError("استحقاق الوحدة يتطلب تحديد Unit.")
            if self.subject and self.unit.subject_id != self.subject_id:
                raise ValidationError("الوحدة لا تنتمي للمادة المحددة.")
            if self.assessment:
                raise ValidationError("استحقاق الوحدة يجب ألا يحدد اختبار.")

        elif self.scope_type == ScopeType.ASSESSMENT:
            if not self.assessment:
                raise ValidationError("استحقاق الاختبار يتطلب تحديد Assessment.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_scope_type_display()})"


class PlanEntitlement(models.Model):
    plan = models.ForeignKey(
        "subscriptions.SubscriptionPlan",
        on_delete=models.CASCADE,
        related_name="plan_entitlements",
    )
    entitlement = models.ForeignKey(
        Entitlement,
        on_delete=models.CASCADE,
        related_name="plan_entitlements",
    )
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "entitlements_plan_entitlements"
        unique_together = ("plan", "entitlement")
        verbose_name = "استحقاق الخطة"
        verbose_name_plural = "استحقاقات الخطط"

    def __str__(self):
        return f"{self.plan.name} -> {self.entitlement.name}"


class UserEntitlement(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_entitlements",
    )
    study_enrollment = models.ForeignKey(
        "curriculum.StudyEnrollment",
        on_delete=models.CASCADE,
        related_name="user_entitlements",
    )
    entitlement = models.ForeignKey(
        Entitlement,
        on_delete=models.CASCADE,
        related_name="user_entitlements",
    )
    source = models.CharField(max_length=50, default="administrative")
    reason = models.TextField(blank=True, default="")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_user_entitlements",
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_user_entitlements",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    usage_count = models.PositiveIntegerField(default=0)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "entitlements_user_entitlements"
        verbose_name = "استحقاق المستخدم"
        verbose_name_plural = "استحقاقات المستخدمين"

    def __str__(self):
        return f"{self.user} - {self.entitlement.name}"


class FreeAccessPolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grade = models.ForeignKey("curriculum.Grade", on_delete=models.CASCADE, related_name="free_policies")
    section = models.ForeignKey("curriculum.Section", on_delete=models.CASCADE, related_name="free_policies")
    subject = models.ForeignKey("curriculum.Subject", on_delete=models.CASCADE, null=True, blank=True, related_name="free_policies")
    academic_year = models.ForeignKey(
        "curriculum.AcademicYear", on_delete=models.CASCADE,
        null=True, blank=True, related_name="free_access_policies",
    )
    free_unit = models.ForeignKey(
        "curriculum.Unit",
        on_delete=models.CASCADE,
        related_name="free_access_policies",
        null=True,
        blank=True,
    )
    subject_summaries_free = models.BooleanField(default=True)
    free_ministerial_count = models.PositiveSmallIntegerField(default=2)
    free_subject_training_count = models.PositiveSmallIntegerField(default=1)
    free_subject_custom_generations = models.PositiveSmallIntegerField(default=1)
    free_mock_generations = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "entitlements_free_access_policies"
        verbose_name = "سياسة الوصول المجاني"
        verbose_name_plural = "سياسات الوصول المجاني"
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "grade", "section", "subject"],
                name="unique_free_policy_per_subject_year",
            )
        ]

    def clean(self):
        super().clean()
        if self.subject:
            if not self.grade_id:
                self.grade_id = self.subject.grade_id
            if not self.section_id:
                self.section_id = self.subject.section_id

            if self.grade_id and str(self.subject.grade_id) != str(self.grade_id):
                raise ValidationError("المادة لا تنتمي للصف المحدد في سياسة الوصول المجاني.")
            if self.section_id and str(self.subject.section_id) != str(self.section_id):
                raise ValidationError("المادة لا تنتمي للقسم المحدد في سياسة الوصول المجاني.")

        if self.free_unit:
            if self.subject_id and str(self.free_unit.subject_id) != str(self.subject_id):
                raise ValidationError("الوحدة المجانية يجب أن تتبع المادة المحددة.")
            if self.free_unit.status != "published":
                raise ValidationError("الوحدة المجانية يجب أن تكون منشورة غير مؤرشفة.")

    def save(self, *args, **kwargs):
        if self.subject_id and not self.free_unit_id:
            from apps.curriculum.models import Unit
            self.free_unit = Unit.objects.filter(
                subject_id=self.subject_id, status="published",
            ).order_by("sort_order", "id").first()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        unit_name = self.free_unit.title if self.free_unit else "غير محددة"
        subject_name = self.subject.name_ar if self.subject else "عام"
        return f"{subject_name} -> {unit_name} (مجاني)"
