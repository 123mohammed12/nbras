from django import forms

from apps.imports.models import ImportOperation


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": ".json,.zip"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_one = super().clean
        return [clean_one(item, initial) for item in data] if isinstance(data, (list, tuple)) else [clean_one(data, initial)]


class ContentImportForm(forms.Form):
    CONTENT_CHOICES = [
        ("auto", "اكتشاف آمن تلقائيًا"),
        ("exams", "نماذج وزارية"),
        ("summaries", "ملخصات"),
        ("smart_cards", "بطاقات ذكية"),
    ]

    files = MultipleFileField(label="ملفات JSON أو ZIP")
    content_type = forms.ChoiceField(label="نوع المحتوى", choices=CONTENT_CHOICES, initial="auto")
    operation = forms.ChoiceField(label="طريقة التنفيذ", choices=ImportOperation.choices, initial=ImportOperation.VALIDATE)
