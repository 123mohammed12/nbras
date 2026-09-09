from django import forms

from apps.accounts.models import normalize_phone
from apps.curriculum.models import ContentStatus, Subject
from apps.subscriptions.models import SubscriptionPlan


class ActivationCodeBatchGenerationForm(forms.Form):
    plan = forms.ModelChoiceField(
        label="الباقة",
        queryset=SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order", "name"),
    )
    quantity = forms.IntegerField(label="الكمية", min_value=1, max_value=5000, initial=100)
    batch_code = forms.CharField(label="معرف الدفعة", max_length=50, required=False)
    code_expires_at = forms.DateTimeField(
        label="انتهاء الرموز",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )


class DirectSubscriptionActivationForm(forms.Form):
    student_phone = forms.CharField(label="رقم هاتف الطالب", max_length=32)
    plan = forms.ModelChoiceField(
        label="الباقة",
        queryset=SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order", "name"),
    )
    subjects = forms.ModelMultipleChoiceField(
        label="المواد الجديدة",
        queryset=Subject.objects.filter(status=ContentStatus.PUBLISHED).order_by(
            "grade__sort_order", "section__sort_order", "sort_order", "name_ar"
        ),
        required=False,
        help_text="اختر فقط المواد الجديدة المطلوبة. باقة جميع المواد لا تحتاج اختياراً.",
    )
    reason = forms.CharField(
        label="سبب التفعيل",
        widget=forms.Textarea(attrs={"rows": 3}),
        min_length=3,
        help_text="مطلوب لسجل التدقيق.",
    )

    def clean_student_phone(self):
        return normalize_phone(self.cleaned_data["student_phone"])
