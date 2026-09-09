"""Validated, atomic import pipeline used by both Django Admin and commands."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone
from django.conf import settings

from apps.assessments.models import Assessment, AssessmentItem, AssessmentType, AssessmentVersion, ShufflePolicy
from apps.attempts.models import AssessmentAttempt
from apps.content.models import Flashcard, FlashcardDeck, Summary, SummaryType
from apps.curriculum.models import Grade, Lesson, Section, Subject, Term, Unit
from apps.curriculum.models.subject import ContentStatus
from apps.curriculum.models.term import build_scoped_term_id
from apps.ministerial_exams.models import ExamRole, MinisterialExam, MinisterialExamItem
from apps.ministerial_exams.utils import normalize_exam_role
from apps.question_bank.models import (
    DifficultyLevel,
    Question,
    QuestionAsset,
    QuestionOption,
    QuestionStimulus,
    QuestionStimulusLink,
    QuestionType,
    QuestionVersion,
    SourceType,
)
from apps.question_bank.services import (
    SUPPORTED_PUBLICATION_TYPES,
    approve_question_version,
    publish_question_version,
    send_question_version_to_review,
    validate_question_options,
)


MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_JSON_BYTES = 5 * 1024 * 1024
ALLOWED_STATUSES = set(ContentStatus.values)


class ContentImportError(ValidationError):
    pass


def _raw_question_checksum(raw):
    canonical = {
        "question_text": raw.get("question_text"),
        "explanation": raw.get("explanation"),
        "correct_answer": str(raw.get("correct_answer", "")).strip().upper(),
        "points": str(Decimal(str(raw.get("points", 1)))),
        "options": [
            {
                "key": str(item.get("key", "")).strip().upper(),
                "text": item.get("text"),
                "image_path": item.get("image_path"),
                "sort_order": item.get("sort_order", index),
            }
            for index, item in enumerate(raw.get("options", []), 1)
        ],
        "question_images": [
            item.get("path") if isinstance(item, dict) else item
            for item in raw.get("question_images", [])
        ],
        "stimulus_ids": list(map(str, raw.get("stimulus_ids", []))),
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _stored_question_checksum(version):
    raw = {
        "question_text": version.question_text,
        "explanation": version.explanation,
        "correct_answer": (version.answer_key or {}).get("correct_answer"),
        "points": version.points,
        "options": [
            {
                "key": item.option_key,
                "text": item.option_text,
                "image_path": item.option_image_path.name if item.option_image_path else None,
                "sort_order": item.sort_order,
            }
            for item in version.options.order_by("sort_order")
        ],
        "question_images": [
            item.file_path.name for item in version.assets.order_by("sort_order")
        ],
        "stimulus_ids": [
            str(item.stimulus_id) for item in version.stimulus_links.order_by("sort_order")
        ],
    }
    return _raw_question_checksum(raw)


@dataclass(frozen=True)
class ImportSource:
    name: str
    content: bytes


def sources_from_paths(paths: list[str | Path]) -> list[ImportSource]:
    sources = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            for child in sorted(path.rglob("*.json")):
                sources.append(ImportSource(str(child), child.read_bytes()))
        else:
            sources.append(ImportSource(str(path), path.read_bytes()))
    return expand_sources(sources)


def sources_from_uploads(uploaded_files) -> list[ImportSource]:
    return expand_sources([ImportSource(upload.name, upload.read()) for upload in uploaded_files])


def expand_sources(sources: list[ImportSource]) -> list[ImportSource]:
    expanded = []
    for source in sources:
        suffix = Path(source.name).suffix.lower()
        if suffix == ".json":
            if len(source.content) > MAX_JSON_BYTES:
                raise ContentImportError(f"{source.name}: حجم JSON أكبر من الحد المسموح.")
            expanded.append(source)
            continue
        if suffix != ".zip":
            raise ContentImportError(f"{source.name}: المسموح JSON أو ZIP فقط.")
        if len(source.content) > MAX_ARCHIVE_BYTES:
            raise ContentImportError(f"{source.name}: حجم ZIP أكبر من الحد المسموح.")
        try:
            with zipfile.ZipFile(io.BytesIO(source.content)) as archive:
                json_entries = [entry for entry in archive.infolist() if not entry.is_dir() and entry.filename.lower().endswith(".json")]
                if not json_entries:
                    raise ContentImportError(f"{source.name}: لا يحتوي ZIP على ملفات JSON.")
                if sum(entry.file_size for entry in json_entries) > MAX_ARCHIVE_BYTES:
                    raise ContentImportError(f"{source.name}: المحتوى المفكوك أكبر من الحد المسموح.")
                for entry in json_entries:
                    if entry.file_size > MAX_JSON_BYTES:
                        raise ContentImportError(f"{source.name}:{entry.filename}: ملف كبير جدًا.")
                    expanded.append(ImportSource(f"{source.name}:{entry.filename}", archive.read(entry)))
        except zipfile.BadZipFile as exc:
            raise ContentImportError(f"{source.name}: ملف ZIP غير صالح.") from exc
    if not expanded:
        raise ContentImportError("لم يتم العثور على ملفات JSON للاستيراد.")
    return expanded


class ContentBatchImporter:
    """Parse every file, validate the complete batch, then mutate in one transaction."""

    def __init__(
        self,
        sources: list[ImportSource],
        *,
        requested_type: str = "auto",
        operation: str = "validate",
        enforce_quran_scope: bool = True,
    ):
        self.sources = sources
        self.requested_type = requested_type
        self.operation = operation
        self.enforce_quran_scope = enforce_quran_scope
        self.records = []
        self._preview = None

    @property
    def checksum(self):
        digest = hashlib.sha256()
        for source in sorted(self.sources, key=lambda item: item.name):
            digest.update(source.name.encode("utf-8"))
            digest.update(source.content)
        return digest.hexdigest()

    def preview(self) -> dict:
        if self._preview is not None:
            return self._preview
        report = {
            "content_type": None,
            "operation": self.operation,
            "scope": [],
            "files": len(self.sources),
            "exams": 0,
            "questions": 0,
            "summaries": 0,
            "summaries_by_type": {},
            "decks": 0,
            "cards": 0,
            "created": 0,
            "updated": 0,
            "new_versions": 0,
            "unchanged": 0,
            "valid": 0,
            "invalid": 0,
            "deleted": 0,
            "archived": 0,
            "skipped": 0,
            "failed": 0,
            "attempts_found": 0,
            "errors": [],
            "warnings": [],
        }
        seen = {}
        for source in self.sources:
            try:
                data = json.loads(source.content.decode("utf-8-sig"))
                if not isinstance(data, dict) or not data:
                    raise ContentImportError("يجب أن يكون جذر الملف كائن JSON غير فارغ.")
                content_type = self._detect_type(data)
                if self.requested_type != "auto" and content_type != self.requested_type:
                    raise ContentImportError(f"نوع المحتوى المكتشف {content_type} لا يطابق النوع المختار {self.requested_type}.")
                identity = self._identity(content_type, data)
                fingerprint = json.dumps(data, ensure_ascii=False, sort_keys=True)
                duplicate = seen.get((content_type, identity))
                if duplicate:
                    if duplicate[1] == fingerprint:
                        report["skipped"] += 1
                        report["warnings"].append(f"{source.name}: نسخة مطابقة للملف {duplicate[0]} وتم تجاهلها.")
                        continue
                    raise ContentImportError(f"المعرف الطبيعي مكرر بمحتوى مختلف عن {duplicate[0]}.")
                seen[(content_type, identity)] = (source.name, fingerprint)
                self._validate_record(content_type, data, source.name, report)
                self.records.append((content_type, data, source.name))
                report["valid"] += 1
            except (UnicodeDecodeError, json.JSONDecodeError, ContentImportError, ValidationError, ValueError) as exc:
                report["failed"] += 1
                report["invalid"] += 1
                message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
                report["errors"].append(f"{source.name}: {message}")

        types = sorted({item[0] for item in self.records})
        report["content_type"] = types[0] if len(types) == 1 else "mixed"
        report["scope"] = sorted({
            f"{data.get('grade_id', '3s')}/{data.get('section_id', '3s_sci')}/{data.get('term_id', 'fy')}/{data.get('subject_id')}"
            for _, data, _ in self.records
        })
        if not report["errors"]:
            self._forecast(report)
        self._preview = report
        return report

    def execute(self) -> dict:
        report = dict(self.preview())
        report["errors"] = list(report["errors"])
        report["warnings"] = list(report["warnings"])
        if report["errors"]:
            raise ContentImportError(report["errors"])
        if self.operation == "validate":
            return report
        report.update(created=0, updated=0, new_versions=0, unchanged=0, deleted=0, archived=0)
        with transaction.atomic():
            exam_records = [item for item in self.records if item[0] == "exams"]
            if exam_records and self.operation == "replace_scope":
                self._replace_exam_scope(exam_records, report)
            for content_type, data, _source_name in self.records:
                if content_type == "exams":
                    self._import_exam(data, report)
                elif content_type == "summaries":
                    self._import_summary(data, report)
                else:
                    self._import_deck(data, report)
        return report

    def _detect_type(self, data):
        if "exam_id" in data and isinstance(data.get("questions"), list):
            return "exams"
        if "summary_type" in data and "body" in data:
            return "summaries"
        if isinstance(data.get("deck"), dict) and isinstance(data.get("cards"), list):
            return "smart_cards"
        raise ContentImportError("تعذر اكتشاف نوع المحتوى من عقد JSON.")

    def _identity(self, content_type, data):
        if content_type == "exams":
            return str(data.get("exam_id") or "")
        if content_type == "summaries":
            return "|".join(str(data.get(key) or "") for key in ("subject_id", "unit_id", "lesson_id", "summary_type", "title"))
        deck = data.get("deck", {})
        return "|".join(str(value or "") for value in (data.get("subject_id"), data.get("unit_id"), data.get("lesson_id"), deck.get("title")))

    def _require(self, data, fields):
        missing = [field for field in fields if data.get(field) in (None, "")]
        if missing:
            raise ContentImportError(f"حقول إلزامية ناقصة: {', '.join(missing)}")

    def _validate_hierarchy(self, data, *, allow_missing_lesson=False):
        self._require(data, ["subject_id"])
        subject = Subject.objects.filter(pk=data["subject_id"]).select_related("grade", "section").first()
        if not subject:
            raise ContentImportError(f"subject_id غير موجود: {data['subject_id']}")
        if self.enforce_quran_scope and (subject.grade_id != "3s" or subject.section_id != "3s_sci"):
            raise ContentImportError("المادة لا تنتمي إلى الصف الثالث الثانوي/القسم العلمي.")
        unit = None
        if data.get("unit_id"):
            unit = Unit.objects.filter(pk=data["unit_id"]).first()
            if not unit:
                raise ContentImportError(f"unit_id غير موجود: {data['unit_id']}")
            if unit.subject_id != subject.id:
                raise ContentImportError(f"الوحدة {unit.id} لا تنتمي إلى المادة {subject.id}.")
        lesson = None
        if data.get("lesson_id"):
            lesson = Lesson.objects.filter(pk=data["lesson_id"]).first()
            if not lesson:
                raise ContentImportError(f"lesson_id غير موجود: {data['lesson_id']}")
            if not unit or lesson.unit_id != unit.id:
                raise ContentImportError(f"الدرس {lesson.id} لا ينتمي إلى الوحدة المحددة.")
        elif not allow_missing_lesson and data.get("unit_id"):
            raise ContentImportError("lesson_id مطلوب لهذا النوع.")
        return subject, unit, lesson

    def _validate_record(self, content_type, data, source_name, report):
        if content_type == "exams":
            required = ["exam_id", "grade_id", "section_id", "subject_id", "year", "model_number"]
            if self.enforce_quran_scope:
                required.append("term_id")
            self._require(data, required)
            if self.enforce_quran_scope and (data["grade_id"] != "3s" or data["section_id"] != "3s_sci" or data["subject_id"] != "3s_sci_quran"):
                raise ContentImportError("استبدال النماذج مقيد بنطاق قرآن الثالث الثانوي العلمي.")
            subject, _, _ = self._validate_hierarchy(data, allow_missing_lesson=True)
            term = self._resolve_term(data.get("term_id"), subject)
            if self.enforce_quran_scope and not term:
                raise ContentImportError(f"term_id غير موجود: {data['term_id']}")
            if term and (term.grade_id != subject.grade_id or term.section_id != subject.section_id):
                raise ContentImportError(f"الترم {term.id} لا يطابق صف/قسم المادة.")
            if not isinstance(data.get("questions"), list) or not data["questions"]:
                raise ContentImportError("قائمة questions فارغة أو غير صالحة.")
            numbers = set()
            stimulus_ids = {str(item.get("stimulus_id")) for item in data.get("stimuli", [])}
            for question in data["questions"]:
                question_required = ["question_number", "question_type", "difficulty", "question_text"]
                if self.enforce_quran_scope:
                    question_required.extend(["unit_id", "lesson_id"])
                self._require(question, question_required)
                if question["question_number"] in numbers:
                    raise ContentImportError(f"question_number مكرر: {question['question_number']}")
                numbers.add(question["question_number"])
                self._validate_hierarchy(
                    {"subject_id": data["subject_id"], "unit_id": question.get("unit_id"), "lesson_id": question.get("lesson_id")},
                    allow_missing_lesson=not self.enforce_quran_scope,
                )
                if question["question_type"] not in QuestionType.values:
                    raise ContentImportError(f"question_type غير معروف: {question['question_type']}")
                if question["question_type"] not in SUPPORTED_PUBLICATION_TYPES:
                    report["warnings"].append(
                        f"السؤال {question['question_number']}: نوع legacy محفوظ لكنه غير مؤهل للنشر/الاختيار في AR-10."
                    )
                if question["difficulty"] not in DifficultyLevel.values:
                    raise ContentImportError(f"difficulty غير مدعوم: {question['difficulty']}")
                try:
                    points = Decimal(str(question.get("points", 1)))
                except Exception as exc:
                    raise ContentImportError("Question points must be numeric.") from exc
                if points <= 0:
                    raise ContentImportError("Question points must be greater than zero.")
                options = question.get("options", [])
                correct = str(question.get("correct_answer", "")).strip().upper()
                if question["question_type"] in SUPPORTED_PUBLICATION_TYPES:
                    try:
                        validate_question_options(
                            question_type=question["question_type"],
                            options_data=[{
                                "option_key": str(option.get("key", "")).strip().upper(),
                                "option_text": option.get("text"),
                                "option_image_path": option.get("image_path"),
                                "is_correct": str(option.get("key", "")).strip().upper() == correct,
                            } for option in options],
                        )
                    except ValidationError as exc:
                        raise ContentImportError(
                            f"السؤال {question['question_number']}: {'; '.join(exc.messages)}"
                        ) from exc
                elif question["question_type"] == QuestionType.ESSAY and options:
                    raise ContentImportError("السؤال المقالي legacy لا يجب أن يحتوي خيارات.")
                unknown = set(map(str, question.get("stimulus_ids", []))) - stimulus_ids
                if unknown:
                    raise ContentImportError(f"السؤال {question['question_number']} يشير إلى stimuli غير موجودة: {sorted(unknown)}")
            report["exams"] += 1
            report["questions"] += len(data["questions"])
            return

        if content_type == "summaries":
            self._require(data, ["title", "summary_type", "subject_id", "body", "status"])
            if data["summary_type"] not in SummaryType.values:
                raise ContentImportError(f"summary_type غير مدعوم: {data['summary_type']}")
            if data["status"] not in ALLOWED_STATUSES:
                raise ContentImportError(f"status غير مدعوم: {data['status']}")
            needs_lesson = data["summary_type"] == SummaryType.LESSON
            self._validate_hierarchy(data, allow_missing_lesson=not needs_lesson)
            report["summaries"] += 1
            report["summaries_by_type"][data["summary_type"]] = report["summaries_by_type"].get(data["summary_type"], 0) + 1
            return

        self._require(data, ["subject_id", "unit_id", "lesson_id"])
        self._validate_hierarchy(data)
        deck = data.get("deck", {})
        self._require(deck, ["title", "status"])
        if deck["status"] not in ALLOWED_STATUSES:
            raise ContentImportError(f"status غير مدعوم: {deck['status']}")
        if not data.get("cards"):
            raise ContentImportError("قائمة cards فارغة.")
        orders = set()
        for card in data["cards"]:
            self._require(card, ["front_text", "back_text", "sort_order"])
            if card["sort_order"] in orders:
                raise ContentImportError(f"sort_order مكرر للبطاقات: {card['sort_order']}")
            orders.add(card["sort_order"])
        report["decks"] += 1
        report["cards"] += len(data["cards"])

    def _forecast(self, report):
        for content_type, data, _ in self.records:
            if content_type == "exams":
                existing = MinisterialExam.objects.filter(model_code=data["exam_id"]).only("source_checksum").first()
                checksum = hashlib.sha256(
                    json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                if existing and existing.source_checksum == checksum:
                    report["unchanged"] += 1
                    continue
                exists = existing is not None
            elif content_type == "summaries":
                exists = Summary.objects.filter(
                    subject_id=data["subject_id"], unit_id=data.get("unit_id"), lesson_id=data.get("lesson_id"),
                    summary_type=data["summary_type"], title=data["title"],
                ).exists()
            else:
                deck = data["deck"]
                exists = FlashcardDeck.objects.filter(
                    subject_id=data["subject_id"], unit_id=data.get("unit_id"), lesson_id=data.get("lesson_id"), title=deck["title"]
                ).exists()
            report["updated" if exists else "created"] += 1
        if self.operation == "replace_scope" and any(item[0] == "exams" for item in self.records):
            incoming = {item[1]["exam_id"] for item in self.records if item[0] == "exams"}
            old = MinisterialExam.objects.filter(subject_id="3s_sci_quran", term_id="3s_sci_fy")
            attempted = old.filter(assessment__attempts__isnull=False).distinct()
            report["attempts_found"] = AssessmentAttempt.objects.filter(assessment__ministerial_exam__in=old).count()
            report["archived"] = attempted.exclude(model_code__in=incoming).count()
            report["deleted"] = old.exclude(id__in=attempted.values("id")).count()

    def _replace_exam_scope(self, records, report):
        incoming = {data["exam_id"] for _, data, _ in records}
        # Lock only ministerial_exams. PostgreSQL rejects FOR UPDATE on the
        # nullable side introduced by select_related("assessment").
        old = list(MinisterialExam.objects.select_for_update().filter(subject_id="3s_sci_quran", term_id="3s_sci_fy"))
        for exam in old:
            has_attempts = bool(exam.assessment_id and AssessmentAttempt.objects.filter(assessment_id=exam.assessment_id).exists())
            if has_attempts:
                if exam.model_code not in incoming:
                    exam.status = ContentStatus.ARCHIVED
                    exam.save(update_fields=["status", "updated_at"])
                    if exam.assessment:
                        exam.assessment.status = ContentStatus.ARCHIVED
                        exam.assessment.save(update_fields=["status", "updated_at"])
                    report["archived"] += 1
                continue
            question_ids = list(Question.objects.filter(versions__ministerial_items__ministerial_exam=exam).values_list("id", flat=True).distinct())
            assessment = exam.assessment
            exam.delete()
            if assessment:
                assessment.delete()
            Question.objects.filter(id__in=question_ids).delete()
            report["deleted"] += 1

    def _import_exam(self, data, report):
        subject = Subject.objects.get(pk=data["subject_id"])
        term = self._resolve_term(data.get("term_id"), subject)
        role = normalize_exam_role(data.get("role"))
        existing = MinisterialExam.objects.filter(model_code=data["exam_id"]).select_related("assessment").first()
        source_checksum = hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        if existing and existing.source_checksum == source_checksum:
            report["unchanged"] += 1
            return
        created = existing is None
        title = f"اختبار وزاري {subject.name_ar} {data['year']} (نموذج {data['model_number']})"
        if existing:
            exam = existing
            exam.subject, exam.term, exam.exam_year, exam.exam_role = subject, term, int(data["year"]), role
            exam.model_number, exam.title, exam.status = str(data["model_number"]), title, ContentStatus.PUBLISHED
            exam.total_questions = len(data["questions"])
            exam.source_checksum = source_checksum
            exam.save()
            assessment = exam.assessment
        else:
            assessment = None
            exam = MinisterialExam.objects.create(
                model_code=data["exam_id"], subject=subject, term=term, exam_year=int(data["year"]), exam_role=role,
                model_number=str(data["model_number"]), title=title, total_questions=len(data["questions"]),
                source_checksum=source_checksum,
                status=ContentStatus.PUBLISHED, published_at=timezone.now(),
            )
        if assessment is None:
            assessment = Assessment.objects.create(
                title=title, subject=subject, assessment_type=AssessmentType.MINISTERIAL_EXAM,
                description=f"نموذج وزاري رسمي لعام {data['year']}", status=ContentStatus.PUBLISHED, published_at=timezone.now(),
            )
            exam.assessment = assessment
            exam.save(update_fields=["assessment", "updated_at"])
        else:
            assessment.title, assessment.subject, assessment.status = title, subject, ContentStatus.PUBLISHED
            assessment.save()

        AssessmentVersion.objects.filter(assessment=assessment, is_current=True).update(is_current=False)
        version_number = (
            AssessmentVersion.objects.filter(assessment=assessment)
            .aggregate(value=Max("version_number"))["value"] or 0
        ) + 1
        total_points = sum(
            (Decimal(str(raw.get("points", 1))) for raw in data["questions"]),
            Decimal("0.00"),
        )
        official_duration = data.get("duration_minutes")
        seconds_per_question = getattr(settings, "ASSESSMENT_SECONDS_PER_QUESTION", 60)
        version = AssessmentVersion.objects.create(
            assessment=assessment, version_number=version_number, question_count=len(data["questions"]),
            duration_minutes=official_duration,
            allowed_display_modes=["one_by_one", "continuous"],
            default_display_mode="one_by_one",
            feedback_policy="deferred",
            timing_mode="fixed" if official_duration else "calculated",
            seconds_per_question=None if official_duration else seconds_per_question,
            question_shuffle_policy=ShufflePolicy.NEVER, option_shuffle_policy=ShufflePolicy.USER_CHOICE,
            total_points=total_points, is_current=True, published_at=timezone.now(),
        )
        stimuli = {}
        for index, raw in enumerate(data.get("stimuli", []), 1):
            raw_id = str(raw.get("stimulus_id"))
            try:
                stimulus_id = uuid.UUID(raw_id)
            except ValueError:
                stimulus_id = uuid.uuid5(uuid.NAMESPACE_URL, f"smart-teacher:{data['exam_id']}:{raw_id}")
            stimulus, _ = QuestionStimulus.objects.update_or_create(
                id=stimulus_id,
                defaults={"subject": subject, "stimulus_type": raw.get("type", "reading_passage"), "title": raw.get("title"),
                          "text_content": raw.get("text"), "image_path": raw.get("image_path"), "status": ContentStatus.PUBLISHED},
            )
            stimuli[raw_id] = stimulus
        existing_items = {
            item.question_number: item
            for item in MinisterialExamItem.objects.select_for_update()
            .filter(ministerial_exam=exam)
            .select_related("question_version__question")
        }
        # Move existing sort positions out of the way before applying the new
        # order; historical occurrence IDs remain stable.
        MinisterialExamItem.objects.filter(ministerial_exam=exam).update(
            sort_order=F("sort_order") + 100000
        )
        incoming_numbers = set()
        for index, raw in enumerate(data["questions"], 1):
            incoming_numbers.add(raw["question_number"])
            question_points = Decimal(str(raw.get("points", 1)))
            checksum = _raw_question_checksum(raw)
            model_answer = raw.get("model_answer") or raw.get("reference_answer")
            if raw["question_type"] == QuestionType.ESSAY and not model_answer:
                model_answer = raw.get("correct_answer")
            item = existing_items.get(raw["question_number"])
            if item is None:
                question = Question.objects.create(
                    id=uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"smart-teacher:ministerial:{data['exam_id']}:{raw['question_number']}",
                    ),
                    subject=subject, unit_id=raw.get("unit_id"), lesson_id=raw.get("lesson_id"),
                    source_type=SourceType.MINISTERIAL, question_type=raw["question_type"],
                    difficulty=raw["difficulty"], status=ContentStatus.DRAFT,
                    metadata={"import_identity": f"{data['exam_id']}:{raw['question_number']}", "content_checksum": checksum},
                )
                q_version = QuestionVersion.objects.create(
                    question=question, version_number=1, question_text=raw["question_text"],
                    explanation=raw.get("explanation"),
                    answer_key={"correct_answer": raw.get("correct_answer"), "model_answer": model_answer},
                    points=question_points, status=ContentStatus.DRAFT, is_current=False,
                )
            else:
                question = item.question_version.question
                old_version = item.question_version
                stored_checksum = (question.metadata or {}).get("content_checksum") or _stored_question_checksum(old_version)
                question.subject = subject
                question.unit_id = raw.get("unit_id")
                question.lesson_id = raw.get("lesson_id")
                question.question_type = raw["question_type"]
                question.difficulty = raw["difficulty"]
                question.status = ContentStatus.PUBLISHED
                question.metadata = {
                    **(question.metadata or {}),
                    "import_identity": f"{data['exam_id']}:{raw['question_number']}",
                    "content_checksum": checksum,
                }
                question.save()
                if stored_checksum == checksum:
                    q_version = old_version
                    report["unchanged"] += 1
                else:
                    next_number = (
                        question.versions.aggregate(value=Max("version_number"))["value"] or 0
                    ) + 1
                    q_version = QuestionVersion.objects.create(
                        question=question, version_number=next_number,
                        question_text=raw["question_text"], explanation=raw.get("explanation"),
                        answer_key={"correct_answer": raw.get("correct_answer"), "model_answer": model_answer},
                        points=question_points, status=ContentStatus.DRAFT, is_current=False,
                    )
                    report["new_versions"] += 1

            if q_version.published_at is None:
                for image_order, image in enumerate(raw.get("question_images", []), 1):
                    image_path = image.get("path") if isinstance(image, dict) else image
                    if image_path:
                        QuestionAsset.objects.create(
                            question_version=q_version, file_path=image_path, sort_order=image_order,
                        )
            correct = str(raw.get("correct_answer", "")).strip().upper()
            keys = [str(option["key"]).strip().upper() for option in raw.get("options", [])]
            if q_version.published_at is None:
                for option_order, option in enumerate(raw.get("options", []), 1):
                    key = str(option["key"]).strip().upper()
                    QuestionOption.objects.create(
                        question_version=q_version, option_key=key, option_text=option.get("text"),
                        option_image_path=option.get("image_path"),
                        sort_order=option.get("sort_order", option_order), is_correct=key == correct,
                    )
                for stimulus_order, stimulus_id in enumerate(raw.get("stimulus_ids", [])):
                    QuestionStimulusLink.objects.create(
                        stimulus=stimuli[str(stimulus_id)], question_version=q_version,
                        sort_order=stimulus_order,
                    )
            if item is None:
                item = MinisterialExamItem.objects.create(
                    ministerial_exam=exam, question_version=q_version,
                    question_number=raw["question_number"], sort_order=index,
                    points=question_points, official_options_order=keys,
                )
            else:
                item.question_version = q_version
                item.sort_order = index
                item.points = question_points
                item.official_options_order = keys
                item.save(update_fields=["question_version", "sort_order", "points", "official_options_order"])
            if q_version.published_at is None:
                if raw["question_type"] in SUPPORTED_PUBLICATION_TYPES:
                    send_question_version_to_review(version=q_version)
                    approve_question_version(version=q_version)
                    publish_question_version(version=q_version)
                else:
                    # Preserve legacy content and freeze it, while explicitly
                    # excluding it from all AR-10 publication/selection pools.
                    question.versions.filter(is_current=True).exclude(pk=q_version.pk).update(is_current=False)
                    q_version.status = ContentStatus.ARCHIVED
                    q_version.is_current = True
                    q_version.published_at = timezone.now()
                    q_version.save(update_fields=["status", "is_current", "published_at"])
                    question.current_version = q_version
                    question.status = ContentStatus.ARCHIVED
                    question.retired_at = timezone.now()
                    question.save(update_fields=["current_version", "status", "retired_at", "updated_at"])
            AssessmentItem.objects.create(
                assessment_version=version, question_version=q_version, ministerial_exam_item=item,
                sort_order=index, points=question_points, official_options_order=keys,
            )
        stale = [item for number, item in existing_items.items() if number not in incoming_numbers]
        for item in stale:
            Question.objects.filter(pk=item.question_version.question_id).update(
                status=ContentStatus.ARCHIVED, retired_at=timezone.now()
            )
        report["archived"] += len(stale)
        exam.total_points = total_points
        exam.save(update_fields=["total_points", "updated_at"])
        report["created" if created else "updated"] += 1

    def _resolve_term(self, raw_term_id, subject):
        if not raw_term_id:
            return None
        scoped_id = build_scoped_term_id(section_id=subject.section_id, term_id=raw_term_id)
        term = Term.objects.filter(pk=scoped_id).first()
        if term:
            return term
        # Transitional compatibility for tests and databases not migrated yet.
        return Term.objects.filter(
            pk=raw_term_id,
            grade_id=subject.grade_id,
            section_id=subject.section_id,
        ).first()

    def _import_summary(self, data, report):
        lookup = {
            "subject_id": data["subject_id"], "unit_id": data.get("unit_id"), "lesson_id": data.get("lesson_id"),
            "summary_type": data["summary_type"], "title": data["title"],
        }
        defaults = {
            "body": data["body"], "file_path": data.get("file_path"), "status": data.get("status", ContentStatus.PUBLISHED),
            "sort_order": data.get("sort_order", 0), "is_downloadable": data.get("is_downloadable", True),
        }
        summary, created = Summary.objects.update_or_create(**lookup, defaults=defaults)
        report["created" if created else "updated"] += 1

    def _import_deck(self, data, report):
        raw_deck = data["deck"]
        lookup = {
            "subject_id": data["subject_id"], "unit_id": data.get("unit_id"), "lesson_id": data.get("lesson_id"), "title": raw_deck["title"],
        }
        deck, created = FlashcardDeck.objects.update_or_create(
            **lookup,
            defaults={"description": raw_deck.get("description", ""), "sort_order": raw_deck.get("sort_order", 0), "status": raw_deck.get("status", ContentStatus.PUBLISHED)},
        )
        incoming_orders = set()
        for raw in data["cards"]:
            incoming_orders.add(raw["sort_order"])
            Flashcard.objects.update_or_create(
                deck=deck, sort_order=raw["sort_order"],
                defaults={"front_text": raw["front_text"], "back_text": raw["back_text"], "explanation": raw.get("explanation"),
                          "difficulty": raw.get("difficulty", DifficultyLevel.MEDIUM), "is_active": raw.get("is_active", True)},
            )
        deck.cards.exclude(sort_order__in=incoming_orders).update(is_active=False)
        report["created" if created else "updated"] += 1
