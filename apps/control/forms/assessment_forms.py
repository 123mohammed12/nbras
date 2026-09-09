import json
from django import forms
from django.core.exceptions import ValidationError
from apps.curriculum.models import ContentStatus, Subject, Unit, Lesson, Grade
from apps.ministerial_exams.models import MinisterialExam, ExamRole
from apps.assessments.models import (
    AssessmentBlueprintVersion,
    TrainingBatchScope,
    AssessmentType,
)
from apps.question_bank.models import SourceType, DifficultyLevel, QuestionType


class MinisterialExamFilterForm(forms.Form):
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.filter(status=ContentStatus.PUBLISHED).order_by("grade__sort_order", "sort_order", "name_ar"),
        required=False,
        empty_label="جميع المواد",
        widget=forms.Select(attrs={"class": "form-control form-select-sm", "id": "id_filter_subject"})
    )
    exam_year = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "placeholder": "السنة (مثال: 2024)"})
    )
    exam_role = forms.ChoiceField(
        choices=[("", "جميع الأدوار")] + list(ExamRole.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    status = forms.ChoiceField(
        choices=[("", "جميع الحالات")] + list(ContentStatus.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "بحث بالرمز أو العنوان..."})
    )


class MinisterialItemReorderForm(forms.Form):
    """
    Form to accept JSON payload of item IDs in desired sort order.
    Format: {"items": [{"id": "<uuid>", "sort_order": 1, "question_number": 1}, ...]}
    """
    reorder_data = forms.CharField(widget=forms.HiddenInput())

    def clean_reorder_data(self):
        raw = self.cleaned_data["reorder_data"]
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValidationError("بيانات الترتيب يجب أن تكون قائمة.")
            return parsed
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValidationError(f"تنسيق البيانات غير صالح: {exc}")


class LessonBatchFilterForm(forms.Form):
    grade = forms.ModelChoiceField(
        queryset=Grade.objects.filter(is_active=True).order_by("sort_order"),
        required=False,
        empty_label="جميع الصفوف",
        widget=forms.Select(attrs={"class": "form-control form-select-sm", "id": "id_filter_grade"})
    )
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.filter(status=ContentStatus.PUBLISHED).order_by("sort_order"),
        required=False,
        empty_label="جميع المواد",
        widget=forms.Select(attrs={"class": "form-control form-select-sm", "id": "id_filter_subject"})
    )
    unit = forms.ModelChoiceField(
        queryset=Unit.objects.filter(status=ContentStatus.PUBLISHED).order_by("sort_order"),
        required=False,
        empty_label="جميع الوحدات",
        widget=forms.Select(attrs={"class": "form-control form-select-sm", "id": "id_filter_unit"})
    )
    lesson = forms.ModelChoiceField(
        queryset=Lesson.objects.filter(status=ContentStatus.PUBLISHED).order_by("sort_order"),
        required=False,
        empty_label="اختر الدرس للمزامنة",
        widget=forms.Select(attrs={"class": "form-control form-select-sm", "id": "id_filter_lesson"})
    )


class TrainingBatchFilterForm(forms.Form):
    scope_type = forms.ChoiceField(
        choices=[("", "جميع النطاقات")] + list(TrainingBatchScope.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.filter(status=ContentStatus.PUBLISHED).order_by("sort_order", "name_ar"),
        required=False,
        empty_label="جميع المواد",
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "بحث بمفتاح النطاق أو اسم المادة..."})
    )


class MockBlueprintFilterForm(forms.Form):
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.filter(status=ContentStatus.PUBLISHED).order_by("sort_order", "name_ar"),
        required=False,
        empty_label="جميع المواد",
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    status = forms.ChoiceField(
        choices=[("", "جميع الحالات")] + list(ContentStatus.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-control form-select-sm"})
    )
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "بحث بالعنوان أو المفتاح..."})
    )


class MockBlueprintVersionDraftForm(forms.ModelForm):
    """
    Form to edit permitted operational fields on a DRAFT AssessmentBlueprintVersion.
    Published versions are immutable.
    """
    unit_distribution_json = forms.CharField(
        label="توزيع الوحدات (JSON)",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 3, "dir": "ltr"})
    )
    difficulty_distribution_json = forms.CharField(
        label="توزيع مستويات الصعوبة (JSON)",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 3, "dir": "ltr"})
    )
    question_type_distribution_json = forms.CharField(
        label="توزيع أنواع الأسئلة (JSON)",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 3, "dir": "ltr"})
    )
    selection_buckets_json = forms.CharField(
        label="دلاء الاختيار المشتركة (Authoritative Selection Buckets JSON)",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 6, "dir": "ltr"})
    )

    class Meta:
        model = AssessmentBlueprintVersion
        fields = [
            "title",
            "question_count",
            "duration_minutes",
            "total_points",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "question_count": forms.NumberInput(attrs={"class": "form-control"}),
            "duration_minutes": forms.NumberInput(attrs={"class": "form-control"}),
            "total_points": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.status == ContentStatus.PUBLISHED:
                for field in self.fields.values():
                    field.disabled = True
            self.fields["unit_distribution_json"].initial = json.dumps(self.instance.unit_distribution or {}, ensure_ascii=False, indent=2)
            self.fields["difficulty_distribution_json"].initial = json.dumps(self.instance.difficulty_distribution or {}, ensure_ascii=False, indent=2)
            self.fields["question_type_distribution_json"].initial = json.dumps(self.instance.question_type_distribution or {}, ensure_ascii=False, indent=2)
            self.fields["selection_buckets_json"].initial = json.dumps(self.instance.selection_buckets or [], ensure_ascii=False, indent=2)

    def clean_unit_distribution_json(self):
        raw = self.cleaned_data.get("unit_distribution_json", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValidationError("يجب أن يكون كائن JSON بصيغة قاموس.")
            return parsed
        except json.JSONDecodeError as exc:
            raise ValidationError(f"تنسيق JSON غير صالح: {exc}")

    def clean_difficulty_distribution_json(self):
        raw = self.cleaned_data.get("difficulty_distribution_json", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValidationError("يجب أن يكون كائن JSON بصيغة قاموس.")
            return parsed
        except json.JSONDecodeError as exc:
            raise ValidationError(f"تنسيق JSON غير صالح: {exc}")

    def clean_question_type_distribution_json(self):
        raw = self.cleaned_data.get("question_type_distribution_json", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValidationError("يجب أن يكون كائن JSON بصيغة قاموس.")
            return parsed
        except json.JSONDecodeError as exc:
            raise ValidationError(f"تنسيق JSON غير صالح: {exc}")

    def clean_selection_buckets_json(self):
        raw = self.cleaned_data.get("selection_buckets_json", "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValidationError("يجب أن يكون مصفوفة JSON من الدلاء.")
            return parsed
        except json.JSONDecodeError as exc:
            raise ValidationError(f"تنسيق JSON غير صالح: {exc}")

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.unit_distribution = self.cleaned_data["unit_distribution_json"]
        instance.difficulty_distribution = self.cleaned_data["difficulty_distribution_json"]
        instance.question_type_distribution = self.cleaned_data["question_type_distribution_json"]
        instance.selection_buckets = self.cleaned_data["selection_buckets_json"]
        if commit:
            instance.save()
        return instance
