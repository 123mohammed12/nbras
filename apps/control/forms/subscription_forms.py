from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import normalize_phone
from apps.curriculum.models import (
    AcademicYear, ContentStatus, Grade, Section, Subject, Unit,
)
from apps.entitlements.models import Entitlement, FreeAccessPolicy
from apps.subscriptions.models import (
    ActivationCodeBatch, ActivationCodeStatus, PackageTierType,
    SubscriptionPlan, SubscriptionSource, SubscriptionStatus,
)


class StudentSubscriptionSearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "بحث بالهاتف أو الكود العام للارتباط بالأكاديمي...",
        })
    )


class SubscriptionFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("", "جميع الحالات")] + list(SubscriptionStatus.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    source = forms.ChoiceField(
        choices=[("", "جميع المصادر")] + list(SubscriptionSource.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all().order_by("-starts_at"),
        required=False,
        empty_label="جميع الأعوام",
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    plan = forms.ModelChoiceField(
        queryset=SubscriptionPlan.objects.all().order_by("sort_order", "name"),
        required=False,
        empty_label="جميع الباقات",
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "بحث بالهاتف أو الكود العام...",
        })
    )


class DirectActivationForm(forms.Form):
    student_phone = forms.CharField(
        label="رقم هاتف الطالب",
        max_length=32,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "+967...",
            "autocomplete": "off",
        }),
    )
    plan = forms.ModelChoiceField(
        label="الخطة / الباقة",
        queryset=SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order", "name"),
        widget=forms.Select(attrs={"class": "form-control form-select", "id": "id_activation_plan"}),
    )
    subjects = forms.ModelMultipleChoiceField(
        label="المواد المختارة (لباقات عدد المواد)",
        queryset=Subject.objects.filter(status=ContentStatus.PUBLISHED).order_by(
            "grade__sort_order", "section__sort_order", "sort_order", "name_ar"
        ),
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-control",
            "size": "8",
            "id": "id_activation_subjects",
        }),
        help_text="اختر المواد المطلوبة إذا كانت الباقة ذات عدد محدد من المواد. باقة جميع المواد تشمل كامل مواد التخصص تلقائياً.",
    )
    reason = forms.CharField(
        label="سبب التفعيل الإداري",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 3,
            "placeholder": "اكتب سبب التفعيل الإداري المباشر للتوثيق في سجل التدقيق...",
        }),
        min_length=3,
        help_text="حقل إلزامي لتوثيق العملية في سجل التدقيق (SubscriptionAudit).",
    )

    def clean_student_phone(self):
        raw = self.cleaned_data.get("student_phone", "").strip()
        if not raw:
            raise ValidationError("رقم هاتف الطالب مطلوب.")
        try:
            return normalize_phone(raw)
        except Exception:
            return raw


class ActivationCodeBatchCreateForm(forms.Form):
    plan = forms.ModelChoiceField(
        label="الخطة المرتبطة",
        queryset=SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order", "name"),
        widget=forms.Select(attrs={"class": "form-control form-select"}),
    )
    quantity = forms.IntegerField(
        label="الكمية المطلوبة (1 - 5000)",
        min_value=1,
        max_value=5000,
        initial=50,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    batch_code = forms.CharField(
        label="معرف الدفعة (اختياري - سيولد تلقائياً إن تُرِك فارغاً)",
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "مثال: BATCH-MATH-2024"}),
    )
    code_expires_at = forms.DateTimeField(
        label="تاريخ انتهاء صلاحية الرموز (اختياري)",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
    )


class ActivationCodeFilterForm(forms.Form):
    batch = forms.ModelChoiceField(
        queryset=ActivationCodeBatch.objects.all().order_by("-created_at"),
        required=False,
        empty_label="جميع الدفعات",
        widget=forms.Select(attrs={"class": "form-control form-select-sm"}),
    )
    plan = forms.ModelChoiceField(
        queryset=SubscriptionPlan.objects.all().order_by("sort_order", "name"),
        required=False,
        empty_label="جميع الباقات",
        widget=forms.Select(attrs={"class": "form-control form-select-sm"}),
    )
    status = forms.ChoiceField(
        choices=[("", "جميع الحالات")] + list(ActivationCodeStatus.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-control form-select-sm"}),
    )
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "بحث بالرمز المقنع أو كود الدفعة...",
        }),
    )


class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = [
            "name",
            "code",
            "description",
            "academic_year",
            "grade",
            "section",
            "tier_type",
            "subject_limit",
            "duration_days",
            "price",
            "offer_price",
            "offer_starts_at",
            "offer_ends_at",
            "currency",
            "is_active",
            "is_catalog_visible",
            "sort_order",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control font-monospace"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "academic_year": forms.Select(attrs={"class": "form-control form-select"}),
            "grade": forms.Select(attrs={"class": "form-control form-select"}),
            "section": forms.Select(attrs={"class": "form-control form-select"}),
            "tier_type": forms.Select(attrs={"class": "form-control form-select"}),
            "subject_limit": forms.NumberInput(attrs={"class": "form-control"}),
            "duration_days": forms.NumberInput(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "offer_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "offer_starts_at": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "offer_ends_at": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "currency": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_catalog_visible": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        instance = getattr(self, "instance", None)
        if instance and instance.pk and instance.is_immutable():
            immutable_fields = ["code", "tier_type", "subject_limit", "academic_year", "grade", "section"]
            for field in immutable_fields:
                old_val = getattr(instance, field)
                new_val = cleaned_data.get(field)
                if old_val != new_val:
                    self.add_error(
                        field,
                        "لا يمكن تعديل هذا الحقل الأساسي لوجود اشتراكات أو رموز مستخدمة مرتبطة بهذه الخطة."
                    )
        return cleaned_data


class FreeAccessPolicyForm(forms.ModelForm):
    class Meta:
        model = FreeAccessPolicy
        fields = [
            "academic_year",
            "grade",
            "section",
            "subject",
            "free_unit",
            "subject_summaries_free",
            "free_ministerial_count",
            "free_subject_training_count",
            "free_subject_custom_generations",
            "free_mock_generations",
            "is_active",
        ]
        widgets = {
            "academic_year": forms.Select(attrs={"class": "form-control form-select"}),
            "grade": forms.Select(attrs={"class": "form-control form-select"}),
            "section": forms.Select(attrs={"class": "form-control form-select"}),
            "subject": forms.Select(attrs={"class": "form-control form-select"}),
            "free_unit": forms.Select(attrs={"class": "form-control form-select"}),
            "subject_summaries_free": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "free_ministerial_count": forms.NumberInput(attrs={"class": "form-control"}),
            "free_subject_training_count": forms.NumberInput(attrs={"class": "form-control"}),
            "free_subject_custom_generations": forms.NumberInput(attrs={"class": "form-control"}),
            "free_mock_generations": forms.NumberInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PlanEntitlementManageForm(forms.Form):
    entitlements = forms.ModelMultipleChoiceField(
        queryset=Entitlement.objects.filter(is_active=True).order_by("scope_type", "name"),
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        required=False,
    )
