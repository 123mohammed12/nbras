"""
Operational forms for Curriculum and Content workspace in /control/.
Provides clean, context-aware forms with strict hierarchy validation.
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.curriculum.models import ContentStatus, Subject, Unit, Lesson
from apps.content.models import (
    Summary,
    SummaryType,
    LessonExplanation,
    ContentFormat,
    FlashcardDeck,
    Flashcard,
)


class SummaryControlForm(forms.ModelForm):
    """
    Form for creating and editing educational summaries in /control/.
    Pre-fills and strictly validates subject, unit, and lesson hierarchy.
    """
    subject_id = forms.CharField(widget=forms.HiddenInput(), required=False)
    unit_id = forms.CharField(widget=forms.HiddenInput(), required=False)
    lesson_id = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Summary
        fields = [
            "title",
            "summary_type",
            "body",
            "file_path",
            "sort_order",
            "status",
            "is_downloadable",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-input", "placeholder": "عنوان الملخص"}),
            "summary_type": forms.Select(attrs={"class": "form-select"}),
            "body": forms.Textarea(attrs={
                "class": "form-textarea",
                "rows": 8,
                "placeholder": "محتوى الملخص (يدعم نصوص وتنسيق Markdown)...",
            }),
            "file_path": forms.FileInput(attrs={"class": "form-input"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-input", "min": 0}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "is_downloadable": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
        }
        labels = {
            "title": "عنوان الملخص",
            "summary_type": "نوع الملخص",
            "body": "نص ومحتوى الملخص",
            "file_path": "ملف مرفق (PDF / مستند)",
            "sort_order": "ترتيب العرض",
            "status": "حالة النشر",
            "is_downloadable": "متاح للتحميل في تطبيق الطالب",
        }

    def __init__(self, *args, hierarchy_context=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hierarchy_context = hierarchy_context or {}

        self.fields["sort_order"].required = False
        self.fields["sort_order"].initial = 0

        # Set initial hierarchy context if creating new summary
        if not self.instance.pk and self.hierarchy_context:
            if "subject" in self.hierarchy_context and self.hierarchy_context["subject"]:
                self.fields["subject_id"].initial = self.hierarchy_context["subject"].id
            if "unit" in self.hierarchy_context and self.hierarchy_context["unit"]:
                self.fields["unit_id"].initial = self.hierarchy_context["unit"].id
            if "lesson" in self.hierarchy_context and self.hierarchy_context["lesson"]:
                self.fields["lesson_id"].initial = self.hierarchy_context["lesson"].id

    def clean(self):
        # Resolve hierarchy objects from self.data or context first
        subject_id = self.data.get("subject_id") or (
            self.hierarchy_context.get("subject").id if self.hierarchy_context.get("subject") else None
        )
        unit_id = self.data.get("unit_id") or (
            self.hierarchy_context.get("unit").id if self.hierarchy_context.get("unit") else None
        )
        lesson_id = self.data.get("lesson_id") or (
            self.hierarchy_context.get("lesson").id if self.hierarchy_context.get("lesson") else None
        )

        lesson = Lesson.objects.filter(id=lesson_id).select_related("unit", "unit__subject").first() if lesson_id else None
        unit = Unit.objects.filter(id=unit_id).select_related("subject").first() if unit_id else None
        subject = Subject.objects.filter(id=subject_id).first() if subject_id else None

        if lesson:
            unit = lesson.unit
            subject = unit.subject
        elif unit:
            subject = unit.subject

        # Assign to instance so model full_clean() in super().clean() has the hierarchy links
        if subject:
            self.instance.subject = subject
        if unit:
            self.instance.unit = unit
        if lesson:
            self.instance.lesson = lesson

        cleaned_data = super().clean()

        if cleaned_data.get("sort_order") is None:
            cleaned_data["sort_order"] = 0
            self.instance.sort_order = 0

        body = cleaned_data.get("body")
        file_path = cleaned_data.get("file_path")
        summary_type = cleaned_data.get("summary_type")

        # Must have at least text body or attached file
        if not body and not file_path and not getattr(self.instance, "file_path", None):
            raise ValidationError("يجب إدخال نص الملخص أو إرفاق ملف PDF على الأقل.")

        # Validate required level based on summary type
        if summary_type in [SummaryType.LESSON, SummaryType.QUICK_REVIEW] and not lesson:
            raise ValidationError("ملخص الدرس والمراجعة السريعة يجب أن يتبعا درساً محدداً.")
        elif summary_type == SummaryType.UNIT and not unit:
            raise ValidationError("ملخص الوحدة يجب أن يحدد الوحدة التابع لها.")
        elif summary_type in [SummaryType.SUBJECT, SummaryType.FINAL_REVIEW] and not subject:
            raise ValidationError("ملخص المادة والمراجعة النهائية يجب أن يحددا المادة الدراسية.")

        self.resolved_subject = subject
        self.resolved_unit = unit
        self.resolved_lesson = lesson

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if hasattr(self, "resolved_subject"):
            instance.subject = self.resolved_subject
        if hasattr(self, "resolved_unit"):
            instance.unit = self.resolved_unit
        if hasattr(self, "resolved_lesson"):
            instance.lesson = self.resolved_lesson

        if commit:
            instance.save()
        return instance


class LessonExplanationControlForm(forms.ModelForm):
    """
    Form for authoring and editing the OneToOne LessonExplanation.
    """
    class Meta:
        model = LessonExplanation
        fields = [
            "title",
            "content_format",
            "body",
            "status",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "عنوان الشرح (اختياري - يترك فارغاً لاستخدام عنوان الدرس)",
            }),
            "content_format": forms.Select(attrs={"class": "form-select"}),
            "body": forms.Textarea(attrs={
                "class": "form-textarea",
                "rows": 12,
                "placeholder": "اكتب الشرح التعليمي هنا (يدعم عناوين، فقرات، قوائم، وصيغ رياضية)...",
            }),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "title": "عنوان الشرح",
            "content_format": "تنسيق المحتوى",
            "body": "محتوى الشرح",
            "status": "حالة النشر",
        }


class FlashcardDeckControlForm(forms.ModelForm):
    """
    Form for creating and editing a FlashcardDeck.
    """
    class Meta:
        model = FlashcardDeck
        fields = [
            "title",
            "description",
            "sort_order",
            "status",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-input", "placeholder": "عنوان الحزمة (مثال: بطاقات المفردات)"}),
            "description": forms.Textarea(attrs={"class": "form-textarea", "rows": 3, "placeholder": "وصف الحزمة التعليمية..."}),
            "sort_order": forms.NumberInput(attrs={"class": "form-input", "min": 0}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "title": "عنوان الحزمة",
            "description": "الوصف والهدف التعليمي",
            "sort_order": "ترتيب العرض",
            "status": "حالة النشر",
        }


class FlashcardControlForm(forms.ModelForm):
    """
    Form for creating and editing individual Flashcards within a deck.
    Supports Text, Image, and Image + Text.
    """
    class Meta:
        model = Flashcard
        fields = [
            "front_text",
            "front_image_path",
            "back_text",
            "back_image_path",
            "explanation",
            "difficulty",
            "sort_order",
            "is_active",
        ]
        widgets = {
            "front_text": forms.Textarea(attrs={"class": "form-textarea", "rows": 3, "placeholder": "النص الظاهر على الوجه الأمامي (السؤال / المفهوم)..."}),
            "front_image_path": forms.FileInput(attrs={"class": "form-input"}),
            "back_text": forms.Textarea(attrs={"class": "form-textarea", "rows": 3, "placeholder": "النص الظاهر على الوجه الخلفي (الإجابة / التعريف)..."}),
            "back_image_path": forms.FileInput(attrs={"class": "form-input"}),
            "explanation": forms.Textarea(attrs={"class": "form-textarea", "rows": 2, "placeholder": "توضيح إضافي أو نصيحة تعليمية للطالب (اختياري)..."}),
            "difficulty": forms.Select(choices=[
                ("easy", "سهل"),
                ("medium", "متوسط"),
                ("hard", "صعب"),
            ], attrs={"class": "form-select"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-input", "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
        }
        labels = {
            "front_text": "الوجه الأمامي (نص)",
            "front_image_path": "الوجه الأمامي (صورة اختيارية)",
            "back_text": "الوجه الخلفي (نص الإجابة)",
            "back_image_path": "الوجه الخلفي (صورة اختيارية)",
            "explanation": "شرح توضيحي إضافي",
            "difficulty": "مستوى الصعوبة",
            "sort_order": "ترتيب البطاقة في الحزمة",
            "is_active": "البطاقة فعالة ونشطة",
        }

    def clean(self):
        cleaned_data = super().clean()
        front_text = cleaned_data.get("front_text")
        front_image = cleaned_data.get("front_image_path")
        back_text = cleaned_data.get("back_text")
        back_image = cleaned_data.get("back_image_path")

        has_front = bool(front_text or front_image or getattr(self.instance, "front_image_path", None))
        has_back = bool(back_text or back_image or getattr(self.instance, "back_image_path", None))

        if not has_front:
            self.add_error("front_text", "يجب إدخال نص أو صورة على الأقل للوجه الأمامي للبطاقة.")
        if not has_back:
            self.add_error("back_text", "يجب إدخال نص أو صورة على الأقل للوجه الخلفي للبطاقة.")

        return cleaned_data
