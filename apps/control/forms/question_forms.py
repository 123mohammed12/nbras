"""
Operational forms for Question Bank workspace in /control/.
Provides high-density, context-aware forms with strict hierarchy and options validation.
"""

from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError

from apps.curriculum.models import ContentStatus, Subject, Unit, Lesson, Topic
from apps.question_bank.models import (
    Question,
    QuestionVersion,
    QuestionOption,
    SourceType,
    QuestionType,
    DifficultyLevel,
    PromptLayout,
)
from apps.question_bank.validators import validate_question_hierarchy
from apps.question_bank.services import (
    create_question_version,
    validate_question_options,
)


QUALITY_FLAG_CHOICES = [
    ("", "جميع إشارات الجودة"),
    ("POTENTIAL_ANSWER_KEY_ISSUE", "احتمال خلل في مفتاح الإجابة"),
    ("HIGH_SKIP_RATE", "معدل تخطي مرتفع"),
    ("INEFFECTIVE_DISTRACTOR", "مشتت غير فعال"),
    ("TOO_EASY", "سهل جداً (نسبة حل عالية)"),
    ("TOO_HARD", "صعب جداً (نسبة خطأ عالية)"),
]


class QuestionFilterForm(forms.Form):
    """
    Search and server-side filtering for Question Bank workspace.
    """
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "بحث بنص السؤال أو المعرف...",
            "autocomplete": "off",
        }),
    )
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.select_related("grade", "section").order_by("sort_order", "name_ar"),
        required=False,
        empty_label="جميع المواد",
        widget=forms.Select(attrs={
            "class": "form-control form-control-sm",
            "hx-get": "/control/questions/htmx/units/",
            "hx-target": "#id_unit_container",
            "hx-trigger": "change",
        }),
    )
    unit = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control form-control-sm",
            "id": "id_unit",
            "hx-get": "/control/questions/htmx/lessons/",
            "hx-target": "#id_lesson_container",
            "hx-trigger": "change",
        }),
    )
    lesson = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control form-control-sm",
            "id": "id_lesson",
        }),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", "جميع الحالات")] + list(ContentStatus.choices),
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    source_type = forms.ChoiceField(
        required=False,
        choices=[("", "جميع المصادر")] + list(SourceType.choices),
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    question_type = forms.ChoiceField(
        required=False,
        choices=[("", "جميع الأنواع")] + list(QuestionType.choices),
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    difficulty = forms.ChoiceField(
        required=False,
        choices=[("", "جميع المستويات")] + list(DifficultyLevel.choices),
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    quality_flag = forms.ChoiceField(
        required=False,
        choices=QUALITY_FLAG_CHOICES,
        widget=forms.Select(attrs={"class": "form-control form-control-sm"}),
    )
    year = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            "class": "form-control form-control-sm",
            "placeholder": "السنة الوزارية (مثلاً 2025)",
            "min": 2000,
            "max": 2035,
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subject_id = self.data.get("subject") or self.initial.get("subject")
        unit_choices = [("", "جميع الوحدات")]
        if subject_id:
            units = Unit.objects.filter(subject_id=subject_id).order_by("sort_order", "title")
            unit_choices.extend([(str(u.id), u.title) for u in units])
        self.fields["unit"].choices = unit_choices

        unit_id = self.data.get("unit") or self.initial.get("unit")
        lesson_choices = [("", "جميع الدروس")]
        if unit_id:
            lessons = Lesson.objects.filter(unit_id=unit_id).order_by("sort_order", "title")
            lesson_choices.extend([(str(l.id), l.title) for l in lessons])
        self.fields["lesson"].choices = lesson_choices


class QuestionCreateForm(forms.Form):
    """
    Full-page authoring form to create a new Question and initial Draft QuestionVersion.
    """
    # A. Academic Context
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.select_related("grade", "section").order_by("sort_order", "name_ar"),
        label="المادة الدراسية",
        widget=forms.Select(attrs={
            "class": "form-control",
            "hx-get": "/control/questions/htmx/units/?for_form=1",
            "hx-target": "#form_unit_container",
            "hx-trigger": "change",
        }),
    )
    unit = forms.ModelChoiceField(
        queryset=Unit.objects.none(),
        required=False,
        label="الوحدة الدراسية",
        widget=forms.Select(attrs={
            "class": "form-control",
            "id": "form_unit_select",
            "hx-get": "/control/questions/htmx/lessons/?for_form=1",
            "hx-target": "#form_lesson_container",
            "hx-trigger": "change",
        }),
    )
    lesson = forms.ModelChoiceField(
        queryset=Lesson.objects.none(),
        required=False,
        label="الدرس",
        widget=forms.Select(attrs={"class": "form-control", "id": "form_lesson_select"}),
    )
    topic = forms.ModelChoiceField(
        queryset=Topic.objects.none(),
        required=False,
        label="الموضوع (اختياري)",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    # B. Classification & Source
    source_type = forms.ChoiceField(
        choices=SourceType.choices,
        initial=SourceType.TRAINING,
        label="مصدر السؤال",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    question_type = forms.ChoiceField(
        choices=[
            (QuestionType.MULTIPLE_CHOICE, "اختيار من متعدد"),
            (QuestionType.TRUE_FALSE, "صواب / خطأ"),
        ],
        initial=QuestionType.MULTIPLE_CHOICE,
        label="نوع السؤال",
        widget=forms.Select(attrs={"class": "form-control", "id": "id_question_type"}),
    )
    difficulty = forms.ChoiceField(
        choices=DifficultyLevel.choices,
        initial=DifficultyLevel.MEDIUM,
        label="مستوى الصعوبة",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    points = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        initial=Decimal("1.00"),
        min_value=Decimal("0.25"),
        max_value=Decimal("100.00"),
        label="درجة السؤال",
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.25"}),
    )
    origin_note = forms.CharField(
        required=False,
        label="مرجع المنشأ / المصدر التوثيقي",
        help_text="مثال: كتاب الطالب ص 42، أو بنك تدريب المناهج",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "مصدر السؤال أو بيانات المنشأ"}),
    )

    # C. Question Stem
    prompt_layout = forms.ChoiceField(
        choices=PromptLayout.choices,
        initial=PromptLayout.TEXT_ONLY,
        label="تخطيط نص السؤال",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    question_text = forms.CharField(
        label="نص السؤال",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "placeholder": "اكتب نص السؤال هنا بدقة وبصياغة لغوية سليمة (يدعم نصوص Markdown ومعادلات LaTeX)...",
            "dir": "rtl",
        }),
    )

    # D. Options (A, B, C, D)
    option_a = forms.CharField(
        label="الخيار (أ / A)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "نص الخيار الأول"}),
    )
    option_b = forms.CharField(
        label="الخيار (ب / B)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "نص الخيار الثاني"}),
    )
    option_c = forms.CharField(
        required=False,
        label="الخيار (ج / C)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "نص الخيار الثالث (اختياري للصح/خطأ)"}),
    )
    option_d = forms.CharField(
        required=False,
        label="الخيار (د / D)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "نص الخيار الرابع (اختياري للصح/خطأ)"}),
    )
    correct_option = forms.ChoiceField(
        choices=[("A", "الخيار أ (A)"), ("B", "الخيار ب (B)"), ("C", "الخيار ج (C)"), ("D", "الخيار د (D)")],
        initial="A",
        label="الإجابة الصحيحة المعتمدة",
        widget=forms.RadioSelect(attrs={"class": "correct-option-radio"}),
    )

    # E. Explanations
    short_explanation = forms.CharField(
        required=False,
        label="شرح موجز (تلميح)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "تلميح أو توضيح سريع للإجابة"}),
    )
    explanation = forms.CharField(
        required=False,
        label="الشرح الكامل والتعليل التربوي",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 3,
            "placeholder": "التعليل النموذجي، خطوات الحل، والمرجع المباشر من الدرس...",
            "dir": "rtl",
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subject_id = self.data.get("subject") or self.initial.get("subject")
        if subject_id:
            self.fields["unit"].queryset = Unit.objects.filter(subject_id=subject_id).order_by("sort_order", "title")
        else:
            self.fields["unit"].queryset = Unit.objects.none()

        unit_id = self.data.get("unit") or self.initial.get("unit")
        if unit_id:
            self.fields["lesson"].queryset = Lesson.objects.filter(unit_id=unit_id).order_by("sort_order", "title")
        else:
            self.fields["lesson"].queryset = Lesson.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        subject = cleaned_data.get("subject")
        unit = cleaned_data.get("unit")
        lesson = cleaned_data.get("lesson")
        topic = cleaned_data.get("topic")
        q_type = cleaned_data.get("question_type")
        correct = cleaned_data.get("correct_option")

        # 1. Academic Hierarchy validation
        try:
            validate_question_hierarchy(subject=subject, unit=unit, lesson=lesson, topic=topic)
        except ValidationError as exc:
            self.add_error(None, exc)

        # 2. Options assembly & validation
        options_data = []
        raw_options = [
            ("A", cleaned_data.get("option_a")),
            ("B", cleaned_data.get("option_b")),
            ("C", cleaned_data.get("option_c")),
            ("D", cleaned_data.get("option_d")),
        ]

        if q_type == QuestionType.TRUE_FALSE:
            # For True/False, enforce A=صواب, B=خطأ or validate given
            opt_a = cleaned_data.get("option_a", "").strip() or "صواب"
            opt_b = cleaned_data.get("option_b", "").strip() or "خطأ"
            options_data = [
                {"option_key": "A", "option_text": opt_a, "sort_order": 1, "is_correct": (correct == "A")},
                {"option_key": "B", "option_text": opt_b, "sort_order": 2, "is_correct": (correct == "B")},
            ]
        else:
            for idx, (key, text) in enumerate(raw_options, 1):
                t = (text or "").strip()
                if t:
                    options_data.append({
                        "option_key": key,
                        "option_text": t,
                        "sort_order": idx,
                        "is_correct": (correct == key),
                    })

        try:
            validate_question_options(question_type=q_type, options_data=options_data)
        except ValidationError as exc:
            self.add_error(None, exc)

        cleaned_data["assembled_options"] = options_data
        return cleaned_data

    def save(self, actor=None) -> Question:
        """
        Creates Question and initial Draft QuestionVersion using domain services.
        """
        cleaned = self.cleaned_data
        meta = {}
        if cleaned.get("origin_note"):
            meta["origin"] = cleaned["origin_note"]

        question = Question.objects.create(
            subject=cleaned["subject"],
            unit=cleaned.get("unit"),
            lesson=cleaned.get("lesson"),
            topic=cleaned.get("topic"),
            source_type=cleaned["source_type"],
            question_type=cleaned["question_type"],
            difficulty=cleaned["difficulty"],
            status=ContentStatus.DRAFT,
            created_by=actor,
            metadata=meta,
        )

        version = create_question_version(
            question=question,
            question_text=cleaned["question_text"],
            prompt_layout=cleaned["prompt_layout"],
            short_explanation=cleaned.get("short_explanation"),
            explanation=cleaned.get("explanation"),
            answer_key={"correct_answer": cleaned["correct_option"]},
            points=cleaned["points"],
            created_by=actor,
            options_data=cleaned["assembled_options"],
            set_as_current=True,
        )
        return question


class QuestionEditDraftForm(forms.Form):
    """
    Form for updating authoring fields of an un-frozen Draft QuestionVersion.
    HARD RULE: Cannot be used on a published/frozen QuestionVersion.
    """
    prompt_layout = forms.ChoiceField(
        choices=PromptLayout.choices,
        label="تخطيط نص السؤال",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    question_text = forms.CharField(
        label="نص السؤال",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "placeholder": "نص السؤال...",
            "dir": "rtl",
        }),
    )
    points = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.25"),
        max_value=Decimal("100.00"),
        label="درجة السؤال",
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.25"}),
    )
    option_a = forms.CharField(
        label="الخيار (أ / A)",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    option_b = forms.CharField(
        label="الخيار (ب / B)",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    option_c = forms.CharField(
        required=False,
        label="الخيار (ج / C)",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    option_d = forms.CharField(
        required=False,
        label="الخيار (د / D)",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    correct_option = forms.ChoiceField(
        choices=[("A", "الخيار أ (A)"), ("B", "الخيار ب (B)"), ("C", "الخيار ج (C)"), ("D", "الخيار د (D)")],
        label="الإجابة الصحيحة المعتمدة",
        widget=forms.RadioSelect(attrs={"class": "correct-option-radio"}),
    )
    short_explanation = forms.CharField(
        required=False,
        label="شرح موجز (تلميح)",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    explanation = forms.CharField(
        required=False,
        label="الشرح الكامل والتعليل التربوي",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "dir": "rtl"}),
    )

    def __init__(self, *args, version: QuestionVersion, **kwargs):
        self.version = version
        super().__init__(*args, **kwargs)

        if not self.is_bound:
            self.fields["prompt_layout"].initial = version.prompt_layout
            self.fields["question_text"].initial = version.question_text
            self.fields["points"].initial = version.points
            self.fields["short_explanation"].initial = version.short_explanation
            self.fields["explanation"].initial = version.explanation

            options = {opt.option_key: opt for opt in version.options.all()}
            if "A" in options:
                self.fields["option_a"].initial = options["A"].option_text
            if "B" in options:
                self.fields["option_b"].initial = options["B"].option_text
            if "C" in options:
                self.fields["option_c"].initial = options["C"].option_text
            if "D" in options:
                self.fields["option_d"].initial = options["D"].option_text

            correct_key = (version.answer_key or {}).get("correct_answer")
            if not correct_key:
                for opt in options.values():
                    if opt.is_correct:
                        correct_key = opt.option_key
                        break
            if correct_key:
                self.fields["correct_option"].initial = correct_key

    def clean(self):
        cleaned_data = super().clean()
        if self.version.published_at is not None:
            raise ValidationError("النسخة المنشورة غير قابلة للتعديل؛ أنشئ نسخة جديدة للتعديل.")

        q_type = self.version.question.question_type
        correct = cleaned_data.get("correct_option")

        raw_options = [
            ("A", cleaned_data.get("option_a")),
            ("B", cleaned_data.get("option_b")),
            ("C", cleaned_data.get("option_c")),
            ("D", cleaned_data.get("option_d")),
        ]

        options_data = []
        if q_type == QuestionType.TRUE_FALSE:
            opt_a = (cleaned_data.get("option_a") or "").strip() or "صواب"
            opt_b = (cleaned_data.get("option_b") or "").strip() or "خطأ"
            options_data = [
                {"option_key": "A", "option_text": opt_a, "sort_order": 1, "is_correct": (correct == "A")},
                {"option_key": "B", "option_text": opt_b, "sort_order": 2, "is_correct": (correct == "B")},
            ]
        else:
            for idx, (key, text) in enumerate(raw_options, 1):
                t = (text or "").strip()
                if t:
                    options_data.append({
                        "option_key": key,
                        "option_text": t,
                        "sort_order": idx,
                        "is_correct": (correct == key),
                    })

        try:
            validate_question_options(question_type=q_type, options_data=options_data)
        except ValidationError as exc:
            self.add_error(None, exc)

        cleaned_data["assembled_options"] = options_data
        return cleaned_data

    def save(self) -> QuestionVersion:
        if self.version.published_at is not None:
            raise ValidationError("لا يمكن تعديل نسخة منشورة.")

        cleaned = self.cleaned_data
        self.version.prompt_layout = cleaned["prompt_layout"]
        self.version.question_text = cleaned["question_text"]
        self.version.points = cleaned["points"]
        self.version.short_explanation = cleaned.get("short_explanation")
        self.version.explanation = cleaned.get("explanation")
        self.version.answer_key = {"correct_answer": cleaned["correct_option"]}
        self.version.save(update_fields=[
            "prompt_layout", "question_text", "points", "short_explanation",
            "explanation", "answer_key",
        ])

        # Safely update existing options or recreate them for this draft
        existing_options = {opt.option_key: opt for opt in self.version.options.all()}
        assembled_keys = set()
        for opt_dict in cleaned["assembled_options"]:
            k = opt_dict["option_key"]
            assembled_keys.add(k)
            if k in existing_options:
                opt = existing_options[k]
                opt.option_text = opt_dict["option_text"]
                opt.sort_order = opt_dict["sort_order"]
                opt.is_correct = opt_dict["is_correct"]
                opt.save(update_fields=["option_text", "sort_order", "is_correct"])
            else:
                QuestionOption.objects.create(
                    question_version=self.version,
                    option_key=k,
                    option_text=opt_dict["option_text"],
                    sort_order=opt_dict["sort_order"],
                    is_correct=opt_dict["is_correct"],
                )

        # Delete any removed options (e.g. if user removed C or D)
        for k, opt in existing_options.items():
            if k not in assembled_keys:
                opt.delete()

        return self.version


class QuestionBulkActionForm(forms.Form):
    """
    Form handling safe bulk lifecycle operations from the question list.
    """
    ACTION_VALIDATE = "validate"
    ACTION_SEND_REVIEW = "send_to_review"
    ACTION_APPROVE = "approve"
    ACTION_PUBLISH = "publish"

    ACTION_CHOICES = [
        (ACTION_VALIDATE, "التحقق من الأسئلة المحددة"),
        (ACTION_SEND_REVIEW, "إرسال المسودات المحددة للمراجعة"),
        (ACTION_APPROVE, "اعتماد الأسئلة المراجعة"),
        (ACTION_PUBLISH, "نشر الأسئلة المعتمدة"),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES, widget=forms.HiddenInput())
    selected_ids = forms.CharField(widget=forms.HiddenInput())

    def clean_selected_ids(self):
        data = self.cleaned_data["selected_ids"]
        ids = [i.strip() for i in data.split(",") if i.strip()]
        if not ids:
            raise ValidationError("لم يتم تحديد أي سؤال لتنفيذ الإجراء.")
        return ids
