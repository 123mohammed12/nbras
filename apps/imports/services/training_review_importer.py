import hashlib
import re
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.attempts.models import AttemptQuestion
from apps.content.models import Summary
from apps.curriculum.models import ContentStatus
from apps.question_bank.models import (
    DifficultyLevel,
    Question,
    QuestionOption,
    QuestionType,
    QuestionVersion,
    SourceType,
)
from apps.question_bank.services import (
    approve_question_version,
    publish_question_version,
    send_question_version_to_review,
)


DATASET_KEY = "ar03_training_review_v1"
REVIEW_FOCUS_EXTRA_QUESTIONS = 18


@dataclass(frozen=True)
class GeneratedTrainingQuestion:
    ordinal: int
    question_type: str
    difficulty: str
    text: str
    explanation: str
    options: tuple[tuple[str, str, bool], ...]


def _clean_line(value: str, maximum=260) -> str:
    value = re.sub(r"^[\s*#\-\d.)]+", "", value or "")
    value = re.sub(r"[`*_]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= maximum:
        return value
    clipped = value[:maximum].rsplit(" ", 1)[0].rstrip("،؛:.-")
    return f"{clipped}…"


def _summary_statements(summary) -> list[str]:
    lines = []
    for raw in (summary.body or "").splitlines():
        if re.match(r"^\s*(?:[*-]|\d+[.)])\s+", raw):
            value = _clean_line(raw)
            if 20 <= len(value) <= 280 and value not in lines:
                lines.append(value)
    if not lines:
        paragraphs = re.split(r"[\n.!؟]+", summary.body or "")
        lines = [_clean_line(value) for value in paragraphs if len(_clean_line(value)) >= 20]
    return lines


def _pick_distinct(values, *, excluded, count):
    result = []
    for value in values:
        clean = _clean_line(value)
        if clean and clean not in excluded and clean not in result:
            result.append(clean)
        if len(result) == count:
            break
    return result


def _options_with_correct(correct_value, distractors, correct_index):
    keys = ("A", "B", "C", "D")
    values = list(distractors[:3])
    values.insert(correct_index, correct_value)
    return tuple(
        (key, value, index == correct_index)
        for index, (key, value) in enumerate(zip(keys, values))
    )


def _generated_for_summary(summary, all_summaries, *, expanded=False):
    statements = _summary_statements(summary)
    if not statements:
        return []
    statement = statements[0]
    same_unit = [item for item in all_summaries if item.unit_id == summary.unit_id and item.id != summary.id]
    other_statements = []
    for item in [*same_unit, *all_summaries]:
        other_statements.extend(_summary_statements(item)[:1])
    distractors = _pick_distinct(other_statements, excluded={statement}, count=3)
    lesson_titles = [
        item.lesson.title
        for item in [*same_unit, *all_summaries]
        if item.lesson_id and item.lesson_id != summary.lesson_id
    ]
    title_distractors = _pick_distinct(
        lesson_titles,
        excluded={summary.lesson.title},
        count=3,
    )
    if len(distractors) < 3 or len(title_distractors) < 3:
        return []
    source_label = summary.title
    explanation = f"مبني مباشرة على «{source_label}» ضمن محتوى الدرس المنشور."
    generated = [
        GeneratedTrainingQuestion(
            ordinal=1,
            question_type=QuestionType.MULTIPLE_CHOICE,
            difficulty=DifficultyLevel.MEDIUM,
            text=f"أي عبارة مما يأتي وردت في {source_label}؟",
            explanation=explanation,
            options=tuple(
                (key, value, key == "A")
                for key, value in zip(("A", "B", "C", "D"), (statement, *distractors))
            ),
        ),
        GeneratedTrainingQuestion(
            ordinal=2,
            question_type=QuestionType.MULTIPLE_CHOICE,
            difficulty=DifficultyLevel.EASY,
            text=f"إلى أي درس ينتمي المحتوى الآتي؟\n«{statement}»",
            explanation=explanation,
            options=tuple(
                (key, value, key == "B")
                for key, value in zip(
                    ("A", "B", "C", "D"),
                    (title_distractors[0], summary.lesson.title, *title_distractors[1:]),
                )
            ),
        ),
        GeneratedTrainingQuestion(
            ordinal=3,
            question_type=QuestionType.TRUE_FALSE,
            difficulty=(
                DifficultyLevel.HARD
                if len(statement) >= 120
                else DifficultyLevel.MEDIUM
            ),
            text=f"وفقًا لـ«{source_label}»: {statement}",
            explanation=explanation,
            options=(("A", "صواب", True), ("B", "خطأ", False)),
        ),
    ]
    if not expanded:
        return generated

    # One content-rich published summary supplies a deeper E2E review pool.
    # Every prompt below quotes its source statement verbatim; no academic
    # fact, topic, year, or ministerial occurrence is inferred or fabricated.
    for index, extra_statement in enumerate(statements[1:10]):
        statement_distractors = _pick_distinct(
            other_statements,
            excluded={extra_statement},
            count=3,
        )
        if len(statement_distractors) < 3:
            continue
        recognition_correct_index = index % 4
        lesson_correct_index = (index + 1) % 4
        generated.extend(
            [
                GeneratedTrainingQuestion(
                    ordinal=4 + (index * 2),
                    question_type=QuestionType.MULTIPLE_CHOICE,
                    difficulty=DifficultyLevel.MEDIUM,
                    text=f"أي عبارة من المجموعة الآتية وردت في {source_label}؟",
                    explanation=explanation,
                    options=_options_with_correct(
                        extra_statement,
                        statement_distractors,
                        recognition_correct_index,
                    ),
                ),
                GeneratedTrainingQuestion(
                    ordinal=5 + (index * 2),
                    question_type=QuestionType.MULTIPLE_CHOICE,
                    difficulty=DifficultyLevel.EASY,
                    text=f"إلى أي درس ينتمي المحتوى الآتي؟\n«{extra_statement}»",
                    explanation=explanation,
                    options=_options_with_correct(
                        summary.lesson.title,
                        title_distractors,
                        lesson_correct_index,
                    ),
                ),
            ]
        )
    return generated[: 3 + REVIEW_FOCUS_EXTRA_QUESTIONS]


def _review_focus_summary_id(summaries):
    eligible = [
        summary
        for summary in summaries
        if len(_summary_statements(summary)) >= 10
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda summary: (len(_summary_statements(summary)), str(summary.id)),
    ).id


def _content_checksum(generated):
    raw = "|".join(
        [
            generated.question_type,
            generated.difficulty,
            generated.text,
            generated.explanation,
            *(f"{key}:{text}:{correct}" for key, text, correct in generated.options),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TrainingReviewImporter:
    """Reproducible local review data sourced only from published summaries."""

    def __init__(self, *, subject_id="3s_sci_quran"):
        self.subject_id = subject_id

    def _summaries(self):
        return list(
            Summary.objects.filter(
                subject_id=self.subject_id,
                status=ContentStatus.PUBLISHED,
                lesson__isnull=False,
                lesson__status=ContentStatus.PUBLISHED,
                unit__status=ContentStatus.PUBLISHED,
            )
            .select_related("subject", "unit", "lesson")
            .order_by("unit__sort_order", "lesson__sort_order", "summary_type", "id")
        )

    def preview(self):
        summaries = self._summaries()
        focus_summary_id = _review_focus_summary_id(summaries)
        generated = [
            question
            for summary in summaries
            for question in _generated_for_summary(
                summary,
                summaries,
                expanded=summary.id == focus_summary_id,
            )
        ]
        return {
            "dataset": DATASET_KEY,
            "subject_id": self.subject_id,
            "source_summaries": len(summaries),
            "questions": len(generated),
            "units": len({summary.unit_id for summary in summaries}),
            "focus_summary_id": str(focus_summary_id) if focus_summary_id else None,
            "writes": False,
        }

    @transaction.atomic
    def execute(self):
        summaries = self._summaries()
        focus_summary_id = _review_focus_summary_id(summaries)
        created = updated = unchanged = 0
        question_ids = []
        for summary in summaries:
            provenance = {
                "dataset": DATASET_KEY,
                "content_basis": "curriculum_summary",
                "origin": f"summary:{summary.id}",
                "summary_id": str(summary.id),
                "style": "summary_comprehension",
            }
            for generated in _generated_for_summary(
                summary,
                summaries,
                expanded=summary.id == focus_summary_id,
            ):
                question_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"smart-teacher:{DATASET_KEY}:{summary.id}:{generated.ordinal}",
                )
                question_ids.append(str(question_id))
                checksum = _content_checksum(generated)
                question = Question.objects.filter(id=question_id).first()
                if question is None:
                    question = Question.objects.create(
                        id=question_id,
                        subject=summary.subject,
                        unit=summary.unit,
                        lesson=summary.lesson,
                        source_type=SourceType.TRAINING,
                        question_type=generated.question_type,
                        difficulty=generated.difficulty,
                        status=ContentStatus.DRAFT,
                        metadata={**provenance, "content_checksum": checksum},
                    )
                    version_number = 1
                    created += 1
                else:
                    old_checksum = (question.metadata or {}).get("content_checksum")
                    question.subject = summary.subject
                    question.unit = summary.unit
                    question.lesson = summary.lesson
                    question.source_type = SourceType.TRAINING
                    question.question_type = generated.question_type
                    question.difficulty = generated.difficulty
                    question.status = ContentStatus.PUBLISHED
                    question.approved_at = question.approved_at or timezone.now()
                    question.metadata = {**provenance, "content_checksum": checksum}
                    question.save()
                    if old_checksum == checksum and question.current_version_id:
                        unchanged += 1
                        continue
                    QuestionVersion.objects.filter(question=question, is_current=True).update(is_current=False)
                    version_number = (
                        QuestionVersion.objects.filter(question=question)
                        .order_by("-version_number")
                        .values_list("version_number", flat=True)
                        .first()
                        or 0
                    ) + 1
                    updated += 1
                correct_key = next(key for key, _, correct in generated.options if correct)
                version = QuestionVersion.objects.create(
                    question=question,
                    version_number=version_number,
                    question_text=generated.text,
                    short_explanation=generated.explanation,
                    explanation=generated.explanation,
                    answer_key={"correct_answer": correct_key},
                    points=1,
                    status=ContentStatus.DRAFT,
                    is_current=False,
                )
                QuestionOption.objects.bulk_create(
                    [
                        QuestionOption(
                            question_version=version,
                            option_key=key,
                            option_text=text,
                            sort_order=index,
                            is_correct=correct,
                        )
                        for index, (key, text, correct) in enumerate(generated.options, 1)
                    ]
                )
                send_question_version_to_review(version=version)
                approve_question_version(version=version)
                publish_question_version(version=version)
        return {
            "dataset": DATASET_KEY,
            "subject_id": self.subject_id,
            "source_summaries": len(summaries),
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "questions": created + updated + unchanged,
            "focus_summary_id": str(focus_summary_id) if focus_summary_id else None,
            "question_ids": question_ids,
            "writes": True,
        }

    @transaction.atomic
    def remove(self):
        questions = Question.objects.filter(metadata__dataset=DATASET_KEY)
        used_ids = set(
            AttemptQuestion.objects.filter(question_version__question__in=questions)
            .values_list("question_version__question_id", flat=True)
        )
        now = timezone.now()
        archived_used = questions.filter(id__in=used_ids).exclude(
            status=ContentStatus.ARCHIVED
        ).update(status=ContentStatus.ARCHIVED, retired_at=now)
        archived_unused = questions.exclude(id__in=used_ids).exclude(
            status=ContentStatus.ARCHIVED
        ).update(status=ContentStatus.ARCHIVED, retired_at=now)
        return {
            "dataset": DATASET_KEY,
            "archived_used_questions": archived_used,
            "archived_unused_questions": archived_unused,
            "deleted_rows": 0,
            "batch_membership_preserved": True,
        }
