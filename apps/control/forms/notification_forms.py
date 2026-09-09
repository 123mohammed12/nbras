import json
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.curriculum.models import ContentStatus, Grade, Section, Subject, Unit, Lesson
from apps.content.models import Summary, FlashcardDeck
from apps.attempts.models import AssessmentAttempt
from apps.notifications.actions import validate_action, CONTRACT
from apps.notifications.models import Notification


def describe_action_destination(action_type, payload):
    """
    Produce a user-friendly human readable label for the semantic action destination.
    """
    if not action_type or action_type == Notification.Action.NONE:
        return "رسالة تنبيه فقط (بدون توجيه تفاعلي)"
    if action_type == Notification.Action.OPEN_SETTINGS:
        return "فتح شاشة الإعدادات العامة"
    if action_type == Notification.Action.OPEN_SUBSCRIPTION:
        return "فتح مركز باقات الاشتراك"
    
    try:
        if action_type == Notification.Action.OPEN_SUBJECT and "subject_id" in payload:
            subj = Subject.objects.select_related("grade").filter(pk=payload["subject_id"]).first()
            return f"فتح المادة: {subj.name_ar} ({subj.grade.name_ar})" if subj else "مادة محددة"
        
        if action_type == Notification.Action.OPEN_UNIT and "unit_id" in payload:
            unit = Unit.objects.select_related("subject").filter(pk=payload["unit_id"]).first()
            return f"فتح الوحدة: {unit.title} ({unit.subject.name_ar})" if unit else "وحدة محددة"
            
        if action_type == Notification.Action.OPEN_LESSON and "lesson_id" in payload:
            lesson = Lesson.objects.select_related("unit__subject").filter(pk=payload["lesson_id"]).first()
            return f"فتح الدرس: {lesson.title} - {lesson.unit.subject.name_ar}" if lesson else "درس محدد"
            
        if action_type == Notification.Action.OPEN_RESOURCE and "resource_id" in payload:
            summary = Summary.objects.select_related("lesson__unit__subject").filter(pk=payload["resource_id"]).first()
            return f"فتح الملخص: {summary.title}" if summary else "ملخص دراسي"
            
        if action_type == Notification.Action.OPEN_SMART_CARDS and "deck_id" in payload:
            deck = FlashcardDeck.objects.filter(pk=payload["deck_id"]).first()
            return f"فتح البطاقات الذكية: {deck.title}" if deck else "مجموعة بطاقات ذكية"
            
        if action_type in (Notification.Action.OPEN_ATTEMPT, Notification.Action.OPEN_RESULT) and "attempt_id" in payload:
            attempt = AssessmentAttempt.objects.select_related("user").filter(pk=payload["attempt_id"]).first()
            lbl = "استئناف محاولة" if action_type == Notification.Action.OPEN_ATTEMPT else "عرض نتيجة محاولة"
            return f"{lbl}: #{str(payload['attempt_id'])[:8]} للطالب {attempt.user.phone}" if attempt else f"{lbl} #{str(payload['attempt_id'])[:8]}"
    except Exception:
        pass

    return f"إجراء تفاعلي: {action_type}"


class NotificationDraftForm(forms.ModelForm):
    """
    Form for drafting and configuring operational notifications in /control/.
    """
    selected_users = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        help_text="معرفات الطلاب المحددين مفصولة بفواصل"
    )
    action_payload = forms.CharField(
        widget=forms.HiddenInput(attrs={"id": "id_action_payload_json"}),
        required=False,
        initial="{}"
    )
    action_payload_json = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        initial="{}"
    )

    class Meta:
        model = Notification
        fields = [
            "title",
            "body",
            "category",
            "priority",
            "push_enabled",
            "audience",
            "grade",
            "section",
            "subject",
            "action_type",
            "action_payload",
            "publish_at",
            "expires_at",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control form-control-lg",
                "placeholder": "اكتب عنوان الإشعار المختصر والواضح...",
                "id": "id_title",
                "maxlength": "120",
            }),
            "body": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "اكتب نص الإشعار هنا...",
                "id": "id_body",
                "maxlength": "2000",
            }),
            "category": forms.Select(attrs={
                "class": "form-select",
                "id": "id_category",
            }),
            "priority": forms.Select(attrs={
                "class": "form-select",
                "id": "id_priority",
            }),
            "push_enabled": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_push_enabled",
            }),
            "audience": forms.Select(attrs={
                "class": "form-select",
                "id": "id_audience",
            }),
            "grade": forms.Select(attrs={
                "class": "form-select",
                "id": "id_grade",
            }),
            "section": forms.Select(attrs={
                "class": "form-select",
                "id": "id_section",
            }),
            "subject": forms.Select(attrs={
                "class": "form-select",
                "id": "id_subject",
            }),
            "action_type": forms.Select(attrs={
                "class": "form-select",
                "id": "id_action_type",
            }),
            "publish_at": forms.DateTimeInput(attrs={
                "class": "form-control",
                "type": "datetime-local",
                "id": "id_publish_at",
            }),
            "expires_at": forms.DateTimeInput(attrs={
                "class": "form-control",
                "type": "datetime-local",
                "id": "id_expires_at",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grade"].queryset = Grade.objects.filter(is_active=True).order_by("sort_order")
        self.fields["section"].queryset = Section.objects.filter(is_active=True).select_related("grade").order_by("grade__sort_order", "sort_order")
        self.fields["subject"].queryset = Subject.objects.filter(status=ContentStatus.PUBLISHED).select_related("grade", "section").order_by("grade__sort_order", "sort_order")
        self.fields["grade"].empty_label = "-- اختر الصف الدراسي --"
        self.fields["section"].empty_label = "-- اختر المسار الدراسي --"
        self.fields["subject"].empty_label = "-- اختر المادة الدراسية --"

        if self.instance and self.instance.pk:
            if self.instance.action_payload:
                self.fields["action_payload_json"].initial = json.dumps(self.instance.action_payload, ensure_ascii=False)
            if self.instance.audience == Notification.Audience.USERS:
                user_ids = list(self.instance.users.values_list("pk", flat=True))
                self.fields["selected_users"].initial = ",".join(str(uid) for uid in user_ids)

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get("title", "").strip()
        body = cleaned_data.get("body", "").strip()
        audience = cleaned_data.get("audience")
        grade = cleaned_data.get("grade")
        section = cleaned_data.get("section")
        subject = cleaned_data.get("subject")
        action_type = cleaned_data.get("action_type") or Notification.Action.NONE
        action_payload_raw = cleaned_data.get("action_payload_json", "{}")
        publish_at = cleaned_data.get("publish_at")
        expires_at = cleaned_data.get("expires_at")
        selected_users_raw = cleaned_data.get("selected_users", "")

        if not title:
            self.add_error("title", "عنوان الإشعار مطلوب.")
        if not body:
            self.add_error("body", "نص الإشعار مطلوب.")

        # Audience validation
        if audience in (Notification.Audience.GRADE, Notification.Audience.SECTION) and not grade:
            self.add_error("grade", "يجب تحديد الصف الدراسي لهذا الجمهور.")

        if audience == Notification.Audience.SECTION and not section:
            self.add_error("section", "يجب تحديد المسار الدراسي لهذا الجمهور.")

        if section and grade and section.grade_id != grade.id:
            self.add_error("section", "المسار المختار لا ينتمي إلى الصف الدراسي المحدد.")

        if audience in (Notification.Audience.SUBJECT, Notification.Audience.SUBJECT_ACCESS) and not subject:
            self.add_error("subject", "يجب تحديد المادة الدراسية لهذا الجمهور.")

        if audience == Notification.Audience.USERS:
            user_ids = [uid.strip() for uid in selected_users_raw.split(",") if uid.strip()]
            if not user_ids and not (self.instance and self.instance.pk and self.instance.users.exists()):
                self.add_error("audience", "يجب تحديد مستخدم واحد على الأقل لجمهور المستخدمين المحددين.")
            cleaned_data["user_ids_list"] = user_ids

        # Semantic action validation
        raw_payload = (
            cleaned_data.get("action_payload")
            or cleaned_data.get("action_payload_json")
            or self.data.get("action_payload")
            or self.data.get("action_payload_json")
            or "{}"
        )
        if isinstance(raw_payload, str):
            try:
                payload = json.loads(raw_payload) if raw_payload.strip() else {}
            except Exception:
                payload = {}
        elif isinstance(raw_payload, dict):
            payload = raw_payload
        else:
            payload = {}

        cleaned_data["action_payload"] = payload
        self.instance.action_payload = payload

        try:
            validate_action(action_type, payload)
        except ValidationError as exc:
            msg = exc.message_dict.get("action_payload", ["الوجهة التفاعلية غير صالحة."])[0] if hasattr(exc, "message_dict") else str(exc)
            self.add_error("action_type", msg)
            self.add_error("action_payload", msg)

        # Dates validation
        now = timezone.now()
        if expires_at and expires_at <= (publish_at or now):
            self.add_error("expires_at", "تاريخ انتهاء الصلاحية يجب أن يكون لاحقاً لموعد النشر.")

        return cleaned_data

    def _post_clean(self):
        self.instance.action_payload = self.cleaned_data.get("action_payload", {})
        super()._post_clean()

    def save(self, commit=True, actor=None):
        instance = super().save(commit=False)
        instance.action_payload = self.cleaned_data.get("action_payload", {})
        if actor and not instance.created_by_id:
            instance.created_by = actor

        if commit:
            instance.save()
            if self.cleaned_data.get("audience") == Notification.Audience.USERS:
                user_ids = self.cleaned_data.get("user_ids_list", [])
                if user_ids:
                    instance.users.set(user_ids)
            self.save_m2m()

        return instance
