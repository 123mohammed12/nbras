from django import forms
from pathlib import Path

from apps.imports.models import ImportContentType, ImportOperation, ImportStatus
from apps.imports.services.content_importer import (
    MAX_ARCHIVE_BYTES,
    MAX_JSON_BYTES,
    ContentImportError,
    expand_sources,
)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={
            "accept": ".json,.zip",
            "class": "form-control-file",
            "id": "importFileInput",
        }))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_one = super().clean
        if isinstance(data, (list, tuple)):
            return [clean_one(item, initial) for item in data]
        return [clean_one(data, initial)]


class ControlContentImportForm(forms.Form):
    CONTENT_CHOICES = [
        ("auto", "اكتشاف آمن تلقائيًا من بنية الملف"),
        (ImportContentType.EXAMS, "نماذج وزارية (Exams)"),
        (ImportContentType.SUMMARIES, "ملخصات دروس ووحدات (Summaries)"),
        (ImportContentType.SMART_CARDS, "بطاقات ذكية واستذكار (Smart Cards)"),
    ]

    OPERATION_CHOICES = [
        (ImportOperation.VALIDATE, "تحقق ومعاينة فقط (بدون أي تعديل في البيانات)"),
        (ImportOperation.UPSERT, "إضافة وتحديث تدريجي (Upsert)"),
        (ImportOperation.REPLACE_SCOPE, "استبدال النطاق بالكامل (Replace Scope - عملية حساسة)"),
    ]

    files = MultipleFileField(
        label="ملفات الحزمة (JSON أو أرشيف ZIP)",
        help_text="يدعم ملفات JSON بحد أقصى 5 ميجابايت للملف، أو أرشيف ZIP بحد أقصى 25 ميجابايت.",
    )
    content_type = forms.ChoiceField(
        label="نوع المحتوى المراد استيراده",
        choices=CONTENT_CHOICES,
        initial="auto",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    operation = forms.ChoiceField(
        label="طريقة التنفيذ المطلوبة",
        choices=OPERATION_CHOICES,
        initial=ImportOperation.VALIDATE,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def clean_files(self):
        uploaded_files = self.cleaned_data.get("files")
        if not uploaded_files:
            raise forms.ValidationError("يرجى اختيار ملف واحد على الأقل للاستيراد.")

        total_archive_bytes = 0
        for upload in uploaded_files:
            name = upload.name.lower()
            suffix = Path(name).suffix
            if suffix not in (".json", ".zip"):
                raise forms.ValidationError(f"الملف '{upload.name}' غير مدعوم. المسموح فقط ملفات JSON أو أرشيف ZIP.")

            if suffix == ".json" and upload.size > MAX_JSON_BYTES:
                raise forms.ValidationError(
                    f"حجم ملف JSON '{upload.name}' ({upload.size // (1024*1024)}MB) يتجاوز الحد الأقصى المسموح (5MB)."
                )

            if suffix == ".zip":
                total_archive_bytes += upload.size
                if upload.size > MAX_ARCHIVE_BYTES:
                    raise forms.ValidationError(
                        f"حجم أرشيف ZIP '{upload.name}' ({upload.size // (1024*1024)}MB) يتجاوز الحد الأقصى المسموح (25MB)."
                    )

        if total_archive_bytes > MAX_ARCHIVE_BYTES:
            raise forms.ValidationError("إجمالي حجم ملفات الأرشيف المرفوعة يتجاوز 25 ميجابايت.")

        return uploaded_files


class ReplaceScopeConfirmationForm(forms.Form):
    confirm_replace_scope = forms.BooleanField(
        required=True,
        label="أفهم أن هذه العملية ستستبدل البيانات ضمن النطاق الموضح أعلاه بشكل نهائي ولا يمكن التراجع عنها.",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "replaceScopeCheckbox"}),
        error_messages={
            "required": "يجب تأكيد الموافقة على استبدال النطاق قبل المتابعة.",
        },
    )
    confirm_token = forms.CharField(widget=forms.HiddenInput())


class ImportHistoryFilterForm(forms.Form):
    content_type = forms.ChoiceField(
        required=False,
        choices=[("", "جميع أنواع المحتوى")] + list(ImportContentType.choices),
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    operation = forms.ChoiceField(
        required=False,
        choices=[("", "جميع العمليات")] + list(ImportOperation.choices),
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "جميع الحالات")] + list(ImportStatus.choices),
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "بحث باسم الملف أو المعرف أو الشيكسوم...",
        }),
    )
