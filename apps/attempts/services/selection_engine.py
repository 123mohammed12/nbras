"""Backend-owned, reusable question selection seam for generated attempts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets

from django.conf import settings
from django.db.models import Count, F, OuterRef, Q, Subquery

from apps.attempts.models import AttemptQuestion
from apps.common.exceptions import ApplicationError
from apps.curriculum.models import ContentStatus, Lesson, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import check_resources_access_batch
from apps.ministerial_exams.models import MinisterialExamItem
from apps.question_bank.models import (
    DifficultyLevel, QuestionType, QuestionVersion, SourceType,
)
from apps.subscriptions.models import GeneratedQuestionUse, GenerationMode
from apps.subscriptions.services.generation_access import check_subject_generation_access


SUPPORTED_TYPES = (QuestionType.MULTIPLE_CHOICE, QuestionType.TRUE_FALSE)
SUPPORTED_SOURCES = (SourceType.MINISTERIAL, SourceType.TRAINING)
SCOPE_MODES = ("subject", "units", "lessons")


@dataclass(frozen=True)
class SelectionSpec:
    subject_id: str
    scope_mode: str
    unit_ids: tuple[str, ...]
    lesson_ids: tuple[str, ...]
    sources: tuple[str, ...]
    years: tuple[int, ...]
    difficulties: tuple[str, ...]
    question_types: tuple[str, ...]
    count: int
    mode: str
    duration_minutes: int | None
    ministerial_percentage: int | None
    training_percentage: int | None
    exclude_previously_answered: bool
    selection_buckets: tuple[dict, ...]

    def to_snapshot(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "scope": {
                "mode": self.scope_mode,
                "unit_ids": list(self.unit_ids),
                "lesson_ids": list(self.lesson_ids),
            },
            "sources": list(self.sources),
            "years": list(self.years),
            "difficulties": list(self.difficulties),
            "question_types": list(self.question_types),
            "count": self.count,
            "mode": self.mode,
            "duration_minutes": self.duration_minutes,
            "source_percentages": (
                {
                    SourceType.MINISTERIAL: self.ministerial_percentage,
                    SourceType.TRAINING: self.training_percentage,
                }
                if self.ministerial_percentage is not None else None
            ),
            "exclude_previously_answered": self.exclude_previously_answered,
            "selection_buckets": [dict(bucket) for bucket in self.selection_buckets],
        }


@dataclass(frozen=True)
class SelectionPolicy:
    seed: str
    prefer_unseen: bool = True


@dataclass(frozen=True)
class SelectedIdentity:
    source_type: str
    question_version_id: str
    ministerial_exam_item_id: str | None = None


def normalize_selection_spec(payload: dict) -> SelectionSpec:
    if not isinstance(payload, dict):
        raise ApplicationError("Selection criteria are required.", code="INVALID_SELECTION_SPEC")
    subject_id = str(payload.get("subject_id") or "").strip()
    scope = payload.get("scope") or {}
    scope_mode = str(scope.get("mode") or "").lower()
    unit_ids = _unique_strings(scope.get("unit_ids") or [])
    lesson_ids = _unique_strings(scope.get("lesson_ids") or [])
    sources = tuple(sorted(_unique_strings(payload.get("sources") or [], lowercase=True)))
    years = _unique_ints(payload.get("years") or [], code="INVALID_YEAR")
    difficulties = tuple(sorted(_unique_strings(payload.get("difficulties") or DifficultyLevel.values, lowercase=True)))
    question_types = tuple(sorted(_unique_strings(payload.get("question_types") or SUPPORTED_TYPES, lowercase=True)))
    try:
        count = int(payload.get("count"))
    except (TypeError, ValueError):
        raise ApplicationError("Question count is invalid.", code="INVALID_COUNT")
    mode = str(payload.get("mode") or "practice").lower()
    duration = payload.get("duration_minutes")
    try:
        duration_minutes = None if duration in (None, "", 0) else int(duration)
    except (TypeError, ValueError):
        raise ApplicationError("Duration is invalid.", code="INVALID_DURATION")
    percentages = payload.get("source_percentages")
    ministerial_pct = training_pct = None
    if percentages is not None:
        if not isinstance(percentages, dict):
            raise ApplicationError("Source percentages are invalid.", code="INVALID_PERCENTAGES")
        try:
            ministerial_pct = int(percentages.get(SourceType.MINISTERIAL))
            training_pct = int(percentages.get(SourceType.TRAINING))
        except (TypeError, ValueError):
            raise ApplicationError("Source percentages are invalid.", code="INVALID_PERCENTAGES")

    maximum = max(1, int(getattr(settings, "ASSESSMENT_CUSTOM_MAX_QUESTIONS", 50)))
    if not subject_id or scope_mode not in SCOPE_MODES:
        raise ApplicationError("Academic scope is invalid.", code="INVALID_SCOPE")
    if scope_mode == "subject" and (unit_ids or lesson_ids):
        raise ApplicationError("Whole-subject scope cannot include child identifiers.", code="INVALID_SCOPE")
    if scope_mode == "units" and (not unit_ids or lesson_ids):
        raise ApplicationError("At least one unit is required.", code="INVALID_SCOPE")
    if scope_mode == "lessons" and (not lesson_ids or unit_ids):
        raise ApplicationError("At least one lesson is required.", code="INVALID_SCOPE")
    if not sources or any(value not in SUPPORTED_SOURCES for value in sources):
        raise ApplicationError("Question source is unsupported.", code="INVALID_SOURCE")
    if years and SourceType.MINISTERIAL not in sources:
        raise ApplicationError("Years apply only to ministerial questions.", code="INVALID_YEAR")
    if any(value not in DifficultyLevel.values for value in difficulties):
        raise ApplicationError("Difficulty is unsupported.", code="INVALID_DIFFICULTY")
    if any(value not in SUPPORTED_TYPES for value in question_types):
        raise ApplicationError(
            "Question type is not supported by the current player.",
            code="UNSUPPORTED_TYPE",
            fields={"supported_types": list(SUPPORTED_TYPES)},
        )
    if count < 1:
        raise ApplicationError("Question count must be positive.", code="INVALID_COUNT")
    if count > maximum:
        raise ApplicationError(
            "Question count exceeds the central maximum.", code="COUNT_ABOVE_MAX",
            fields={"maximum": maximum, "requested": count},
        )
    if mode not in ("practice", "exam"):
        raise ApplicationError("Attempt mode is invalid.", code="INVALID_MODE")
    max_duration = int(getattr(settings, "ASSESSMENT_CUSTOM_MAX_DURATION_MINUTES", 300))
    if duration_minutes is not None and not 1 <= duration_minutes <= max_duration:
        raise ApplicationError(
            "Duration is outside the allowed range.", code="INVALID_DURATION",
            fields={"minimum": 1, "maximum": max_duration},
        )
    if percentages is not None:
        if set(sources) != set(SUPPORTED_SOURCES):
            raise ApplicationError("Ratios require a mixed source selection.", code="INVALID_PERCENTAGES")
        if ministerial_pct < 0 or training_pct < 0 or ministerial_pct + training_pct != 100:
            raise ApplicationError("Source percentages must total 100.", code="INVALID_PERCENTAGES")

    raw_buckets = payload.get("selection_buckets") or []
    if not isinstance(raw_buckets, list):
        raise ApplicationError("Selection buckets are invalid.", code="INVALID_SELECTION_BUCKETS")
    selection_buckets = []
    bucket_keys = set()
    for raw in raw_buckets:
        if not isinstance(raw, dict):
            raise ApplicationError("Selection buckets are invalid.", code="INVALID_SELECTION_BUCKETS")
        source = str(raw.get("source") or "").lower()
        unit_id = str(raw.get("unit_id") or "").strip()
        difficulty = str(raw.get("difficulty") or "").lower()
        question_type = str(raw.get("question_type") or "").lower()
        try:
            bucket_count = int(raw.get("count"))
        except (TypeError, ValueError):
            raise ApplicationError("Selection bucket count is invalid.", code="INVALID_SELECTION_BUCKETS")
        key = (source, unit_id, difficulty, question_type)
        if (
            source not in sources
            or not unit_id
            or difficulty not in difficulties
            or question_type not in question_types
            or bucket_count < 1
            or key in bucket_keys
        ):
            raise ApplicationError("Selection bucket is invalid or duplicated.", code="INVALID_SELECTION_BUCKETS")
        bucket_keys.add(key)
        selection_buckets.append({
            "source": source,
            "unit_id": unit_id,
            "difficulty": difficulty,
            "question_type": question_type,
            "count": bucket_count,
        })
    if selection_buckets and sum(bucket["count"] for bucket in selection_buckets) != count:
        raise ApplicationError(
            "Selection bucket counts must equal the requested count.",
            code="INVALID_SELECTION_BUCKETS",
        )

    return SelectionSpec(
        subject_id=subject_id, scope_mode=scope_mode,
        unit_ids=unit_ids, lesson_ids=lesson_ids, sources=sources, years=years,
        difficulties=difficulties, question_types=question_types, count=count,
        mode=mode, duration_minutes=duration_minutes,
        ministerial_percentage=ministerial_pct, training_percentage=training_pct,
        exclude_previously_answered=bool(payload.get("exclude_previously_answered", False)),
        selection_buckets=tuple(selection_buckets),
    )


class SelectionEngine:
    def __init__(self, *, user, enrollment: StudyEnrollment, spec: SelectionSpec, generation_mode=GenerationMode.CUSTOM):
        self.user = user
        self.enrollment = enrollment
        self.spec = spec
        self.generation_mode = generation_mode
        self.generation_access = None
        self.subject = self._validate_scope_and_access()

    def preview(self) -> dict:
        pools = self._pool_queries()
        if self.spec.selection_buckets:
            bucket_rows = self._strict_bucket_availability(pools)
            missing = [row for row in bucket_rows if row["available"] < row["required"]]
            available_total = sum(min(row["required"], row["available"]) for row in bucket_rows)
            return {
                "requested_count": self.spec.count,
                "eligible_count": sum(row["available"] for row in bucket_rows),
                "can_create_exact": not missing,
                "maximum_creatable": available_total,
                "planned_source_distribution": {
                    source: sum(
                        bucket["count"] for bucket in self.spec.selection_buckets
                        if bucket["source"] == source
                    )
                    for source in self.spec.sources
                },
                "source_availability": {
                    source: pools[source].count() for source in self.spec.sources
                },
                "bucket_availability": bucket_rows,
                "missing_buckets": missing,
                "scope_summary": {
                    "subject_id": self.spec.subject_id,
                    "mode": self.spec.scope_mode,
                    "unit_ids": list(self.spec.unit_ids),
                    "lesson_ids": list(self.spec.lesson_ids),
                },
                "warnings": ([] if not missing else [{
                    "code": "MOCK_POOL_INSUFFICIENT",
                    "missing_buckets": missing,
                }]),
            }
        source_counts = {source: pools[source].count() for source in self.spec.sources}
        creatable, planned = self._creatable_plan(source_counts, self.spec.count)
        eligible = sum(source_counts.values())
        breakdown = self._availability_breakdown(pools)
        return {
            "requested_count": self.spec.count,
            "eligible_count": eligible,
            "can_create_exact": creatable == self.spec.count,
            "maximum_creatable": creatable,
            "planned_source_distribution": planned,
            "source_availability": source_counts,
            "year_availability": breakdown["years"],
            "difficulty_availability": breakdown["difficulties"],
            "question_type_availability": breakdown["question_types"],
            "scope_summary": {
                "subject_id": self.spec.subject_id,
                "mode": self.spec.scope_mode,
                "unit_ids": list(self.spec.unit_ids),
                "lesson_ids": list(self.spec.lesson_ids),
            },
            "warnings": ([] if creatable == self.spec.count else [{
                "code": "INSUFFICIENT_POOL",
                "requested": self.spec.count,
                "available": creatable,
            }]),
        }

    def select(self, *, count: int, policy: SelectionPolicy) -> tuple[list[SelectedIdentity], dict]:
        pools = self._pool_queries()
        if self.spec.selection_buckets:
            if count != self.spec.count:
                raise ApplicationError(
                    "Strict selection cannot reduce the requested count.",
                    code="MOCK_POOL_INSUFFICIENT",
                )
            rows = self._strict_bucket_availability(pools)
            missing = [row for row in rows if row["available"] < row["required"]]
            if missing:
                raise ApplicationError(
                    "The current pool cannot satisfy the Mock blueprint.",
                    code="MOCK_POOL_INSUFFICIENT",
                    fields={"missing_buckets": missing},
                )
            selected = []
            for bucket in self.spec.selection_buckets:
                query = self._strict_bucket_query(pools[bucket["source"]], bucket)
                selected.extend(self._pick_bucket(
                    bucket["source"], query, bucket["count"], policy,
                    bucket["difficulty"], bucket["question_type"],
                ))
            selected.sort(key=lambda item: _seed_number(
                policy.seed, item.source_type, item.question_version_id,
                item.ministerial_exam_item_id or "",
            ))
            return selected, {
                "engine_version": 2,
                "selection_seed": policy.seed,
                "prefer_unseen": policy.prefer_unseen,
                "actual_count": len(selected),
                "strict_buckets": rows,
            }
        source_counts = {source: pools[source].count() for source in self.spec.sources}
        creatable, plan = self._creatable_plan(source_counts, count)
        if creatable != count:
            raise ApplicationError(
                "The eligible pool cannot satisfy the requested count.",
                code="INSUFFICIENT_POOL",
                fields={"requested": count, "available": creatable, "distribution": plan},
            )
        selected: list[SelectedIdentity] = []
        for source in self.spec.sources:
            target = plan.get(source, 0)
            if target:
                selected.extend(self._select_source(source, pools[source], target, policy))
        selected.sort(key=lambda item: _seed_number(policy.seed, item.source_type, item.question_version_id, item.ministerial_exam_item_id or ""))
        return selected, {
            "engine_version": 1,
            "selection_seed": policy.seed,
            "prefer_unseen": policy.prefer_unseen,
            "actual_count": len(selected),
            "source_distribution": plan,
        }

    def _validate_scope_and_access(self):
        subject = Subject.objects.filter(id=self.spec.subject_id, status=ContentStatus.PUBLISHED).first()
        if subject is None or str(subject.grade_id) != str(self.enrollment.grade_id) or str(subject.section_id) != str(self.enrollment.section_id):
            raise ApplicationError("Subject is outside the active academic context.", code="INVALID_SCOPE")
        resources = []
        if self.spec.scope_mode == "subject":
            resources = [{"type": "subject", "id": subject.id}]
        elif self.spec.scope_mode == "units":
            units = list(Unit.objects.filter(
                id__in=self.spec.unit_ids, subject=subject, status=ContentStatus.PUBLISHED,
            ).values_list("id", flat=True))
            if {str(value) for value in units} != set(self.spec.unit_ids):
                raise ApplicationError("One or more units are stale or outside the subject.", code="INVALID_SCOPE")
            resources = [{"type": "unit", "id": value} for value in self.spec.unit_ids]
        else:
            lessons = list(Lesson.objects.filter(
                id__in=self.spec.lesson_ids, unit__subject=subject,
                status=ContentStatus.PUBLISHED, unit__status=ContentStatus.PUBLISHED,
            ).values_list("id", flat=True))
            if {str(value) for value in lessons} != set(self.spec.lesson_ids):
                raise ApplicationError("One or more lessons are stale or outside the subject.", code="INVALID_SCOPE")
            resources = [{"type": "lesson", "id": value} for value in self.spec.lesson_ids]
        decisions = check_resources_access_batch(
            user=self.user, enrollment=self.enrollment, resources=resources,
        )
        denied = [str(item["id"]) for item in resources if not decisions[(item["type"], str(item["id"]))].allowed]
        if denied and self.spec.scope_mode == "subject":
            self.generation_access = check_subject_generation_access(
                user=self.user, enrollment=self.enrollment,
                subject=subject, mode=self.generation_mode,
            )
            if self.generation_access.allowed:
                denied = []
        if denied:
            raise ApplicationError(
                "The selected scope contains inaccessible content.",
                code=(self.generation_access.reason_code if self.generation_access else "INACCESSIBLE_SCOPE"),
                status_code=403, fields={"resource_ids": denied},
            )
        return subject

    def _scope_q(self, prefix: str) -> Q:
        if self.spec.scope_mode == "units":
            return Q(**{f"{prefix}unit_id__in": self.spec.unit_ids})
        if self.spec.scope_mode == "lessons":
            return Q(**{f"{prefix}lesson_id__in": self.spec.lesson_ids})
        return Q(**{f"{prefix}subject_id": self.spec.subject_id})

    def _strict_bucket_query(self, pool, bucket):
        prefix = "question_version__question__" if bucket["source"] == SourceType.MINISTERIAL else "question__"
        return pool.filter(**{
            f"{prefix}unit_id": bucket["unit_id"],
            f"{prefix}difficulty": bucket["difficulty"],
            f"{prefix}question_type": bucket["question_type"],
        })

    def _strict_bucket_availability(self, pools):
        unit_ids = {bucket["unit_id"] for bucket in self.spec.selection_buckets}
        valid_units = {
            str(value) for value in Unit.objects.filter(
                id__in=unit_ids, subject=self.subject, status=ContentStatus.PUBLISHED,
            ).values_list("id", flat=True)
        }
        if valid_units != unit_ids:
            raise ApplicationError(
                "A blueprint bucket references a stale academic unit.",
                code="INVALID_SELECTION_BUCKETS",
            )
        rows = []
        for bucket in self.spec.selection_buckets:
            available = self._strict_bucket_query(pools[bucket["source"]], bucket).count()
            rows.append({**bucket, "required": bucket["count"], "available": available})
        return rows

    def _pool_queries(self):
        pools = {}
        used_questions = GeneratedQuestionUse.objects.filter(
            user=self.user,
            academic_year_id=self.enrollment.academic_year_id,
            mode=self.generation_mode,
        ).values("question_id")
        if SourceType.MINISTERIAL in self.spec.sources:
            ministerial = MinisterialExamItem.objects.filter(
                self._scope_q("question_version__question__"),
                ministerial_exam__status=ContentStatus.PUBLISHED,
                question_version__question__status=ContentStatus.PUBLISHED,
                question_version__status=ContentStatus.PUBLISHED,
                question_version__question__source_type=SourceType.MINISTERIAL,
                question_version__question__current_version_id=F("question_version_id"),
                question_version__question__difficulty__in=self.spec.difficulties,
                question_version__question__question_type__in=self.spec.question_types,
            )
            if self.spec.years:
                ministerial = ministerial.filter(ministerial_exam__exam_year__in=self.spec.years)
            ministerial = ministerial.exclude(
                question_version__question_id__in=Subquery(used_questions)
            )
            if self.spec.exclude_previously_answered:
                answered = AttemptQuestion.objects.filter(
                    attempt__user=self.user, answers__isnull=False,
                    ministerial_exam_item__isnull=False,
                ).values("ministerial_exam_item_id")
                ministerial = ministerial.exclude(id__in=Subquery(answered))
            # A logical question can occur in several ministerial models. Keep
            # one eligible occurrence so a generated set never consumes or
            # displays the same stable Question identity twice.
            canonical_occurrence = ministerial.filter(
                question_version__question_id=OuterRef(
                    "question_version__question_id"
                )
            ).order_by("ministerial_exam__exam_year", "id").values("id")[:1]
            ministerial = ministerial.filter(id=Subquery(canonical_occurrence))
            pools[SourceType.MINISTERIAL] = ministerial
        if SourceType.TRAINING in self.spec.sources:
            training = QuestionVersion.objects.filter(
                self._scope_q("question__"),
                question__status=ContentStatus.PUBLISHED,
                status=ContentStatus.PUBLISHED,
                question__source_type=SourceType.TRAINING,
                question__current_version_id=F("id"),
                question__difficulty__in=self.spec.difficulties,
                question__question_type__in=self.spec.question_types,
            ).exclude(question_id__in=Subquery(used_questions))
            if self.spec.exclude_previously_answered:
                answered_questions = AttemptQuestion.objects.filter(
                    attempt__user=self.user, answers__isnull=False,
                    source_type=SourceType.TRAINING,
                ).values("question_version__question_id")
                training = training.exclude(question_id__in=Subquery(answered_questions))
            pools[SourceType.TRAINING] = training
        return pools

    def _creatable_plan(self, available: dict[str, int], requested: int):
        requested = min(requested, self.spec.count)
        if len(self.spec.sources) == 1:
            source = self.spec.sources[0]
            count = min(requested, available.get(source, 0))
            return count, {source: count}
        if self.spec.ministerial_percentage is None:
            for total in range(requested, -1, -1):
                plan = {
                    SourceType.MINISTERIAL: (total + 1) // 2,
                    SourceType.TRAINING: total // 2,
                }
                if all(plan[source] <= available.get(source, 0) for source in SUPPORTED_SOURCES):
                    return total, plan
            return 0, {SourceType.MINISTERIAL: 0, SourceType.TRAINING: 0}
        for total in range(requested, -1, -1):
            plan = self._ratio_plan(total)
            if all(plan[source] <= available.get(source, 0) for source in SUPPORTED_SOURCES):
                return total, plan
        return 0, {SourceType.MINISTERIAL: 0, SourceType.TRAINING: 0}

    def _ratio_plan(self, total):
        # Integer half-up allocation is stable and the remainder is assigned to Training.
        ministerial = (total * self.spec.ministerial_percentage + 50) // 100
        return {SourceType.MINISTERIAL: ministerial, SourceType.TRAINING: total - ministerial}

    def _availability_breakdown(self, pools):
        years, difficulties, question_types = {}, {}, {}
        for source, pool in pools.items():
            if source == SourceType.MINISTERIAL:
                year_rows = pool.values("ministerial_exam__exam_year").annotate(count=Count("id"))
                for row in year_rows:
                    years[str(row["ministerial_exam__exam_year"])] = row["count"]
                rows = pool.values(
                    "question_version__question__difficulty",
                    "question_version__question__question_type",
                ).annotate(count=Count("id"))
                d_key, t_key = "question_version__question__difficulty", "question_version__question__question_type"
            else:
                rows = pool.values("question__difficulty", "question__question_type").annotate(count=Count("id"))
                d_key, t_key = "question__difficulty", "question__question_type"
            for row in rows:
                difficulties[row[d_key]] = difficulties.get(row[d_key], 0) + row["count"]
                question_types[row[t_key]] = question_types.get(row[t_key], 0) + row["count"]
        return {"years": years, "difficulties": difficulties, "question_types": question_types}

    def _select_source(self, source, pool, target, policy):
        if source == SourceType.MINISTERIAL:
            d_key, t_key = "question_version__question__difficulty", "question_version__question__question_type"
        else:
            d_key, t_key = "question__difficulty", "question__question_type"
        rows = list(pool.values(d_key, t_key).annotate(count=Count("id")))
        buckets = [(row[d_key], row[t_key], row["count"]) for row in rows]
        quotas = _balanced_quotas(buckets, target)
        result = []
        for (difficulty, question_type), quota in quotas.items():
            bucket = pool.filter(**{d_key: difficulty, t_key: question_type})
            result.extend(self._pick_bucket(source, bucket, quota, policy, difficulty, question_type))
        return result

    def _pick_bucket(self, source, bucket, quota, policy, difficulty, question_type):
        if quota <= 0:
            return []
        return self._bounded_slice(
            source, bucket, quota, policy.seed,
            difficulty, question_type, "unseen",
        )

    def _bounded_slice(self, source, query, take, seed, *parts):
        total = query.count()
        if not total or not take:
            return []
        take = min(take, total)
        offset = _seed_number(seed, source, *parts) % total
        raw = list(query.order_by("id").values_list("id", "question_version_id")[offset:offset + take]) if source == SourceType.MINISTERIAL else list(query.order_by("id").values_list("id", flat=True)[offset:offset + take])
        if len(raw) < take and offset:
            missing = take - len(raw)
            head = list(query.order_by("id").values_list("id", "question_version_id")[:missing]) if source == SourceType.MINISTERIAL else list(query.order_by("id").values_list("id", flat=True)[:missing])
            raw.extend(head)
        if source == SourceType.MINISTERIAL:
            return [SelectedIdentity(source, str(qv_id), str(item_id)) for item_id, qv_id in raw]
        return [SelectedIdentity(source, str(qv_id)) for qv_id in raw]


def new_selection_policy() -> SelectionPolicy:
    return SelectionPolicy(seed=secrets.token_hex(16))


def _balanced_quotas(buckets, target):
    remaining = {(difficulty, qtype): available for difficulty, qtype, available in buckets}
    result = {key: 0 for key in remaining}
    keys = sorted(remaining)
    while target > 0 and keys:
        next_keys = []
        for key in keys:
            if target == 0:
                break
            if remaining[key] > result[key]:
                result[key] += 1
                target -= 1
            if remaining[key] > result[key]:
                next_keys.append(key)
        keys = next_keys
    return result


def _seed_number(*parts):
    digest = hashlib.sha256("|".join(str(value) for value in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _unique_strings(values, *, lowercase=False):
    if not isinstance(values, (list, tuple)):
        raise ApplicationError("A selection list is invalid.", code="INVALID_SELECTION_SPEC")
    normalized = (str(value).strip() for value in values if str(value).strip())
    if lowercase:
        normalized = (value.lower() for value in normalized)
    return tuple(dict.fromkeys(normalized))


def _unique_ints(values, *, code):
    if not isinstance(values, (list, tuple)):
        raise ApplicationError("A numeric selection list is invalid.", code=code)
    try:
        return tuple(dict.fromkeys(int(value) for value in values))
    except (TypeError, ValueError):
        raise ApplicationError("A numeric selection value is invalid.", code=code)
