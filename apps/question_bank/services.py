from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.curriculum.models import ContentStatus
from apps.question_bank.models import (
    Question,
    QuestionAsset,
    QuestionOption,
    QuestionStimulusLink,
    QuestionType,
    QuestionVersion,
    SourceType,
)
from apps.question_bank.validators import validate_question_hierarchy


SUPPORTED_PUBLICATION_TYPES = {
    QuestionType.MULTIPLE_CHOICE,
    QuestionType.TRUE_FALSE,
}


def _require_permission(actor, codename: str):
    if actor is not None and not actor.has_perm(f"question_bank.{codename}"):
        raise PermissionDenied("ليس لديك الصلاحية المطلوبة لتنفيذ هذه الخطوة.")


def validate_question_version_content(*, question_text, prompt_layout="text_only", assets_count=0):
    has_text = bool(question_text and question_text.strip())
    if not has_text and assets_count == 0:
        raise ValidationError("السؤال يجب أن يحتوي على نص أو ملحق (صورة/جدول/معادلة) واحد على الأقل.")


def validate_question_options(*, question_type, options_data):
    if question_type not in SUPPORTED_PUBLICATION_TYPES:
        raise ValidationError("نوع السؤال غير مدعوم للنشر في AR-10.")
    if not options_data or len(options_data) < 2:
        raise ValidationError("الأسئلة الموضوعية تتطلب خيارين على الأقل.")
    keys = [str(item.get("option_key") or "").strip().upper() for item in options_data]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValidationError("مفاتيح الخيارات مطلوبة ويجب أن تكون ثابتة وفريدة.")
    if sum(bool(item.get("is_correct")) for item in options_data) != 1:
        raise ValidationError("يجب أن يحتوي السؤال على إجابة صحيحة واحدة فقط.")
    if question_type == QuestionType.TRUE_FALSE and (len(options_data) != 2 or keys != ["A", "B"]):
        raise ValidationError("الصواب والخطأ يتطلب خيارين ثابتين A ثم B.")
    if question_type == QuestionType.TRUE_FALSE:
        labels = tuple(str(item.get("option_text") or "").strip().lower() for item in options_data)
        if labels not in {("صواب", "خطأ"), ("صح", "خطأ"), ("true", "false")}:
            raise ValidationError("خيارات الصواب والخطأ يجب أن تكون عقداً ثابتاً: صواب/خطأ.")
    for option in options_data:
        if not (str(option.get("option_text") or "").strip() or option.get("option_image_path")):
            raise ValidationError("خيار الإجابة لا يمكن أن يكون فارغاً.")


def validate_question_for_publication(version: QuestionVersion) -> dict:
    """Return a bounded, Admin-friendly validation report without writing."""
    errors, warnings = [], []
    question = version.question
    try:
        validate_question_hierarchy(
            subject=question.subject, unit=question.unit,
            lesson=question.lesson, topic=question.topic,
        )
    except ValidationError as exc:
        errors.extend(exc.messages)
    for label, resource in (("المادة", question.subject), ("الوحدة", question.unit), ("الدرس", question.lesson)):
        if resource is not None and getattr(resource, "status", ContentStatus.PUBLISHED) != ContentStatus.PUBLISHED:
            errors.append(f"{label} الأكاديمي غير منشور.")
    if question.question_type not in SUPPORTED_PUBLICATION_TYPES:
        errors.append("نوع السؤال غير مدعوم للنشر؛ AR-07 مؤجل.")
    assets = list(version.assets.all())
    try:
        validate_question_version_content(
            question_text=version.question_text,
            prompt_layout=version.prompt_layout,
            assets_count=len(assets),
        )
    except ValidationError as exc:
        errors.extend(exc.messages)
    options = list(version.options.order_by("sort_order", "option_key"))
    if question.question_type in SUPPORTED_PUBLICATION_TYPES:
        try:
            validate_question_options(
                question_type=question.question_type,
                options_data=[{
                    "option_key": item.option_key,
                    "option_text": item.option_text,
                    "option_image_path": item.option_image_path,
                    "is_correct": item.is_correct,
                } for item in options],
            )
        except ValidationError as exc:
            errors.extend(exc.messages)
    correct_keys = [item.option_key for item in options if item.is_correct]
    answer_key = str((version.answer_key or {}).get("correct_answer") or "").strip().upper()
    if correct_keys and answer_key and answer_key != str(correct_keys[0]).upper():
        errors.append("مفتاح الإجابة لا يطابق الخيار الصحيح.")
    if correct_keys and not answer_key:
        errors.append("مفتاح الإجابة المرجعي مطلوب.")
    if version.points is None or version.points <= 0:
        errors.append("درجة السؤال يجب أن تكون أكبر من صفر.")
    if not str(version.explanation or version.short_explanation or "").strip():
        warnings.append("لا يوجد شرح؛ راجع ملاءمة ذلك قبل النشر.")
    for asset in assets:
        if not asset.file_path:
            errors.append(f"ملحق غير صالح: {asset.pk}")
        elif not asset.file_path.storage.exists(asset.file_path.name):
            errors.append(f"ملف الملحق غير موجود: {asset.file_path.name}")
        elif not asset.alt_text:
            warnings.append(f"الملحق {asset.pk} لا يحتوي نصاً بديلاً.")
    for option in options:
        if option.option_image_path and not option.option_image_path.storage.exists(option.option_image_path.name):
            errors.append(f"صورة الخيار غير موجودة: {option.option_image_path.name}")
    provenance = question.metadata or {}
    if question.source_type == SourceType.TRAINING:
        if not (question.created_by_id or provenance.get("origin") or provenance.get("dataset")):
            errors.append("مصدر/منشأ السؤال التدريبي مطلوب.")
    elif question.source_type == SourceType.MINISTERIAL:
        occurrence_exists = version.ministerial_items.exists() or question.versions.filter(
            ministerial_items__isnull=False
        ).exists()
        if not occurrence_exists:
            errors.append("السؤال الوزاري يجب أن يرتبط بوقوع وزاري موثق.")
    else:
        errors.append("AR-10 ينشر حالياً محتوى Training أو Ministerial فقط.")
    latest_number = question.versions.aggregate(value=Max("version_number"))["value"] or 0
    if version.version_number != latest_number:
        errors.append("لا يمكن نشر نسخة قديمة مع وجود نسخة أحدث.")
    return {
        "question_id": str(question.pk),
        "version_id": str(version.pk),
        "version_number": version.version_number,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


@transaction.atomic
def create_question_version(
    *, question: Question, question_text: str | None = None,
    prompt_layout: str = "text_only", short_explanation: str | None = None,
    explanation: str | None = None, answer_key: dict | None = None,
    points: Decimal = Decimal("1.00"), created_by=None,
    options_data: list | None = None, set_as_current: bool = True,
) -> QuestionVersion:
    """Create an editable Draft; never displace an already-published current version."""
    question = Question.objects.select_for_update().get(pk=question.pk)
    validate_question_hierarchy(
        subject=question.subject, unit=question.unit,
        lesson=question.lesson, topic=question.topic,
    )
    latest = question.versions.order_by("-version_number").first()
    next_number = (latest.version_number + 1) if latest else 1
    options_data = options_data or []
    if options_data:
        validate_question_options(question_type=question.question_type, options_data=options_data)
    has_frozen_current = bool(question.current_version_id and question.current_version.published_at)
    make_current = bool(set_as_current and not has_frozen_current)
    if make_current:
        question.versions.filter(is_current=True).update(is_current=False)
    version = QuestionVersion.objects.create(
        question=question, version_number=next_number,
        question_text=question_text, prompt_layout=prompt_layout,
        short_explanation=short_explanation, explanation=explanation,
        answer_key=answer_key or {}, points=points,
        status=ContentStatus.DRAFT, is_current=make_current, created_by=created_by,
    )
    for index, raw in enumerate(options_data, 1):
        QuestionOption.objects.create(
            question_version=version,
            option_key=str(raw.get("option_key") or index).upper(),
            option_text=raw.get("option_text"),
            option_image_path=raw.get("option_image_path"),
            sort_order=raw.get("sort_order", index),
            is_correct=raw.get("is_correct", False),
        )
    if make_current:
        question.current_version = version
        question.status = ContentStatus.DRAFT
        question.save(update_fields=["current_version", "status", "updated_at"])
    return version


@transaction.atomic
def clone_question_version(*, question: Question, actor=None) -> QuestionVersion:
    """Clone authoring fields only, leaving historical associations/current untouched."""
    _require_permission(actor, "change_question")
    question = Question.objects.select_for_update(of=("self",)).select_related("current_version").get(pk=question.pk)
    source = question.current_version
    if source is None:
        raise ValidationError("لا توجد نسخة حالية يمكن نسخها.")
    clone = create_question_version(
        question=question, question_text=source.question_text,
        prompt_layout=source.prompt_layout,
        short_explanation=source.short_explanation, explanation=source.explanation,
        answer_key=dict(source.answer_key or {}), points=source.points,
        created_by=actor,
        options_data=[{
            "option_key": item.option_key, "option_text": item.option_text,
            "option_image_path": item.option_image_path, "sort_order": item.sort_order,
            "is_correct": item.is_correct,
        } for item in source.options.order_by("sort_order")],
        set_as_current=False,
    )
    for asset in source.assets.order_by("sort_order"):
        QuestionAsset.objects.create(
            question_version=clone, asset_type=asset.asset_type,
            asset_role=asset.asset_role, file_path=asset.file_path,
            alt_text=asset.alt_text, caption=asset.caption,
            sort_order=asset.sort_order, width=asset.width, height=asset.height,
        )
    for link in source.stimulus_links.order_by("sort_order"):
        QuestionStimulusLink.objects.create(
            stimulus=link.stimulus, question_version=clone,
            sort_order=link.sort_order, is_required=link.is_required,
        )
    return clone


@transaction.atomic
def send_question_version_to_review(*, version: QuestionVersion, actor=None):
    _require_permission(actor, "change_question")
    version = QuestionVersion.objects.select_for_update(of=("self",)).select_related("question", "question__current_version").get(pk=version.pk)
    if version.status != ContentStatus.DRAFT or version.published_at is not None:
        raise ValidationError("يمكن إرسال النسخ المسودة فقط للمراجعة.")
    report = validate_question_for_publication(version)
    if report["errors"]:
        raise ValidationError(report["errors"])
    now = timezone.now()
    version.status = ContentStatus.UNDER_REVIEW
    version.reviewed_by = actor
    version.reviewed_at = now
    version.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    if not version.question.current_version_id or version.question.current_version.published_at is None:
        Question.objects.filter(pk=version.question_id).update(
            status=ContentStatus.UNDER_REVIEW, reviewed_by=actor, reviewed_at=now,
        )
    return report


@transaction.atomic
def approve_question_version(*, version: QuestionVersion, actor=None):
    _require_permission(actor, "review_question")
    version = QuestionVersion.objects.select_for_update(of=("self",)).select_related("question", "question__current_version").get(pk=version.pk)
    if version.status != ContentStatus.UNDER_REVIEW:
        raise ValidationError("يجب أن تكون النسخة قيد المراجعة قبل الاعتماد.")
    report = validate_question_for_publication(version)
    if report["errors"]:
        raise ValidationError(report["errors"])
    now = timezone.now()
    version.status = ContentStatus.APPROVED
    version.approved_by = actor
    version.approved_at = now
    version.save(update_fields=["status", "approved_by", "approved_at"])
    if not version.question.current_version_id or version.question.current_version.published_at is None:
        Question.objects.filter(pk=version.question_id).update(
            status=ContentStatus.APPROVED, approved_by=actor, approved_at=now,
        )
    return report


@transaction.atomic
def publish_question_version(*, version: QuestionVersion, actor=None, require_approval=True):
    _require_permission(actor, "publish_question")
    version = (
        QuestionVersion.objects.select_for_update(of=("self",))
        .select_related("question", "question__subject", "question__unit", "question__lesson", "question__topic")
        .get(pk=version.pk)
    )
    if version.published_at is not None:
        return validate_question_for_publication(version)
    if require_approval and version.status != ContentStatus.APPROVED:
        raise ValidationError("يجب اعتماد النسخة قبل نشرها.")
    report = validate_question_for_publication(version)
    if report["errors"]:
        raise ValidationError(report["errors"])
    question = Question.objects.select_for_update().get(pk=version.question_id)
    question.versions.filter(is_current=True).exclude(pk=version.pk).update(is_current=False)
    now = timezone.now()
    version.status = ContentStatus.PUBLISHED
    version.is_current = True
    version.published_by = actor
    version.published_at = now
    version.save(update_fields=["status", "is_current", "published_by", "published_at"])
    question.current_version = version
    question.status = ContentStatus.PUBLISHED
    question.published_by = actor
    question.published_at = now
    question.retired_at = None
    question.save(update_fields=[
        "current_version", "status", "published_by", "published_at", "retired_at", "updated_at",
    ])
    return report


@transaction.atomic
def retire_question(*, question: Question, actor=None):
    _require_permission(actor, "retire_question")
    question = Question.objects.select_for_update().get(pk=question.pk)
    if question.status != ContentStatus.ARCHIVED:
        question.status = ContentStatus.ARCHIVED
        question.retired_at = timezone.now()
        question.save(update_fields=["status", "retired_at", "updated_at"])
    return question


@transaction.atomic
def set_current_question_version(*, question: Question, version_number: int) -> QuestionVersion:
    question = Question.objects.select_for_update().get(pk=question.pk)
    target = question.versions.filter(version_number=version_number).first()
    if target is None:
        raise ValidationError(f"نسخة السؤال رقم {version_number} غير موجودة.")
    if question.versions.filter(published_at__isnull=False).exists() and target.published_at is None:
        raise ValidationError("لا يمكن جعل مسودة حالية فوق نسخة منشورة؛ استخدم إجراء النشر.")
    question.versions.filter(is_current=True).update(is_current=False)
    target.is_current = True
    target.save(update_fields=["is_current"])
    question.current_version = target
    question.save(update_fields=["current_version", "updated_at"])
    return target
