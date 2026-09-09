import copy
import random
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from django.utils import timezone

from apps.attempts.models import (
    AssessmentAttempt,
    AttemptQuestion,
    AttemptStimulus,
    AttemptQuestionStimulus,
    AttemptAnswer,
    AttemptAnalysis,
    AttemptStatus,
    AttemptType,
    AttemptMode,
)
from apps.attempts.services.snapshots import build_attempt_question_snapshot
from apps.attempts.services.grading import grade_attempt_answer
from apps.assessments.models import (
    Assessment,
    AssessmentVersion,
    AssessmentItem,
    AssessmentType,
)
from apps.curriculum.models import StudyEnrollment
from apps.question_bank.models import QuestionVersion, QuestionOption
from apps.common.exceptions import ApplicationError
from apps.progress.services.attempt_integration import apply_attempt_submission_to_progress
from apps.entitlements.services.access_service import check_attempt_snapshot_access
def start_assessment_attempt(
    *,
    user,
    assessment_id: str,
    mode: str = "exam",
    shuffle_questions: bool | None = None,
    shuffle_options: bool | None = None,
    client_attempt_id: str | None = None,
    idempotency_key: str | None = None,
    selected_item_ids: list[str] | None = None,
    selected_ministerial_item_ids: list[str] | None = None,
    selected_question_version_ids: list[str] | None = None,
    source_scope: dict | None = None,
    preserve_question_order: bool = False,
) -> AssessmentAttempt:
    with transaction.atomic():
        if idempotency_key:
            existing = AssessmentAttempt.objects.filter(user=user, idempotency_key=idempotency_key).first()
            if existing:
                return existing

        enrollment = StudyEnrollment.objects.filter(user=user, is_active=True).first()
        if not enrollment:
            raise ApplicationError("لا يوجد ملف دراسي نشط للمستخدم.", code="NO_ACTIVE_ENROLLMENT")

        assessment = (
            Assessment.objects.select_for_update()
            .filter(id=assessment_id, status="published")
            .first()
        )
        if not assessment:
            raise ApplicationError("الاختبار المحدد غير موجود أو غير منشور.", code="ASSESSMENT_NOT_FOUND")

        # One editable attempt per user/source. Locking the assessment row makes
        # this safe for concurrent taps even when their idempotency keys differ.
        active_attempts = list(
            AssessmentAttempt.objects.filter(
                user=user,
                assessment=assessment,
                attempt_questions__isnull=False,
                status__in=[
                    AttemptStatus.CREATED,
                    AttemptStatus.IN_PROGRESS,
                    AttemptStatus.PAUSED,
                ],
            ).distinct().order_by("-created_at")
        )
        active = next(
            (
                candidate
                for candidate in active_attempts
                if source_scope is None or candidate.source_scope == source_scope
            ),
            None,
        )
        if active is not None:
            if not check_attempt_snapshot_access(user=user, attempt=active).allowed:
                raise ApplicationError("المحاولة غير متاحة.", code="ATTEMPT_NOT_FOUND", status_code=404)
            return active

        # Central Entitlements Access Check
        from apps.entitlements.services.access_service import check_resource_access
        decision = check_resource_access(
            user=user,
            enrollment=enrollment,
            resource_type="assessment",
            resource_id=str(assessment.id),
        )
        if not decision.allowed:
            if decision.reason_code in {
                "ACADEMIC_SCOPE_MISMATCH",
                "ACADEMIC_CONTEXT_MISMATCH",
            }:
                raise ApplicationError("هذا الاختبار يخص صفاً دراسياً مختلفاً عن صفك المسجل.", code="ACADEMIC_LEVEL_MISMATCH")
            raise ApplicationError(
                "هذا المحتوى غير متاح ضمن وصولك الحالي.",
                code=decision.reason_code, status_code=403,
            )

        # Academic Level Verification: assessment subject grade must match enrollment grade
        if assessment.subject and hasattr(assessment.subject, "grade_id") and assessment.subject.grade_id:
            if enrollment.grade_id and str(assessment.subject.grade_id) != str(enrollment.grade_id):
                raise ApplicationError("هذا الاختبار يخص صفاً دراسياً مختلفاً عن صفك المسجل.", code="ACADEMIC_LEVEL_MISMATCH")

        version = AssessmentVersion.objects.filter(assessment=assessment, is_current=True).first()
        if not version:
            version = AssessmentVersion.objects.filter(assessment=assessment).order_by("-version_number").first()

        if not version:
            raise ApplicationError("لا توجد نسخة نشطة لهذا الاختبار.", code="NO_ACTIVE_VERSION")

        # Validate requested mode
        if mode not in [AttemptMode.PRACTICE, AttemptMode.EXAM]:
            raise ApplicationError(f"وضع المحاولة غير مسموح: {mode}", code="INVALID_MODE")

        allowed_modes = version.allowed_attempt_modes or ["practice", "exam"]
        if mode not in allowed_modes:
            raise ApplicationError(f"وضع المحاولة '{mode}' غير متاح لهذه النسخة من الاختبار.", code="MODE_NOT_ALLOWED")

        is_full_ministerial = assessment.assessment_type == AssessmentType.MINISTERIAL_EXAM

        # A full historical model always preserves its official question order.
        q_shuffle = False
        if preserve_question_order:
            q_shuffle = False
        elif not is_full_ministerial and version.question_shuffle_policy == "always":
            q_shuffle = True
        elif not is_full_ministerial and version.question_shuffle_policy == "user_choice" and shuffle_questions is True:
            q_shuffle = True

        o_shuffle = False
        if version.option_shuffle_policy == "always":
            o_shuffle = True
        elif version.option_shuffle_policy == "user_choice" and shuffle_options is True:
            o_shuffle = True

        supplied_selections = sum(
            value is not None
            for value in (
                selected_item_ids,
                selected_ministerial_item_ids,
                selected_question_version_ids,
            )
        )
        if supplied_selections > 1:
            raise ApplicationError(
                "Only one assessment selection may be supplied.",
                code="INVALID_ASSESSMENT_SELECTION",
            )
        normalized_ids = None
        if selected_item_ids is not None:
            normalized_ids = [str(item_id) for item_id in selected_item_ids]
            if len(normalized_ids) != len(set(normalized_ids)):
                raise ApplicationError(
                    "Assessment selection contains duplicate questions.",
                    code="INVALID_ASSESSMENT_SELECTION",
                )
        direct_occurrence_ids = None
        direct_question_version_ids = None
        if selected_ministerial_item_ids is not None:
            direct_occurrence_ids = [str(value) for value in selected_ministerial_item_ids]
            if len(direct_occurrence_ids) != len(set(direct_occurrence_ids)):
                raise ApplicationError(
                    "Assessment selection contains duplicate questions.",
                    code="INVALID_ASSESSMENT_SELECTION",
                )
            from apps.ministerial_exams.models import MinisterialExamItem

            direct_query = MinisterialExamItem.objects.filter(
                id__in=direct_occurrence_ids,
                question_version__question__status="published",
                ministerial_exam__status="published",
            )
            scope = source_scope or {}
            if scope.get("kind") == "lesson_ministerial":
                direct_query = direct_query.filter(
                    question_version__question__lesson_id=scope.get("source_id")
                )
            elif scope.get("kind") == "unit_ministerial":
                direct_query = direct_query.filter(
                    question_version__question__unit_id=scope.get("source_id"),
                    ministerial_exam_id=scope.get("ministerial_exam_id"),
                )
            items = list(
                direct_query.select_related(
                    "ministerial_exam", "question_version__question"
                ).prefetch_related(
                    "question_version__options",
                    "question_version__stimulus_links__stimulus",
                    "question_version__assets",
                )
            )
            by_id = {str(item.id): item for item in items}
            if any(item_id not in by_id for item_id in direct_occurrence_ids):
                raise ApplicationError(
                    "Ministerial selection contains an unrelated question.",
                    code="INVALID_ASSESSMENT_SELECTION",
                )
            items = [by_id[item_id] for item_id in direct_occurrence_ids]
        elif selected_question_version_ids is not None:
            direct_question_version_ids = [str(value) for value in selected_question_version_ids]
            if len(direct_question_version_ids) != len(set(direct_question_version_ids)):
                raise ApplicationError(
                    "Training selection contains duplicate questions.",
                    code="INVALID_ASSESSMENT_SELECTION",
                )
            direct_query = QuestionVersion.objects.filter(
                id__in=direct_question_version_ids,
                question__source_type="training",
                question__status="published",
            )
            scope = source_scope or {}
            if scope.get("kind") == "lesson_training":
                direct_query = direct_query.filter(
                    question__lesson_id=scope.get("source_id")
                )
            elif scope.get("kind") == "unit_training":
                direct_query = direct_query.filter(
                    question__unit_id=scope.get("source_id")
                )
            elif scope.get("kind") == "subject_training":
                direct_query = direct_query.filter(
                    question__subject_id=scope.get("source_id")
                )
            else:
                raise ApplicationError(
                    "Training selection requires an explicit curriculum scope.",
                    code="INVALID_ASSESSMENT_SELECTION",
                )
            versions = list(
                direct_query.select_related("question").prefetch_related(
                    "options", "stimulus_links__stimulus", "assets"
                )
            )
            by_id = {str(version.id): version for version in versions}
            if any(value not in by_id for value in direct_question_version_ids):
                raise ApplicationError(
                    "Training selection contains an unrelated question.",
                    code="INVALID_ASSESSMENT_SELECTION",
                )
            items = [by_id[value] for value in direct_question_version_ids]
        else:
            item_query = AssessmentItem.objects.filter(
                assessment_version=version,
                question_version__question__status="published",
            )
            if normalized_ids is not None:
                item_query = item_query.filter(id__in=normalized_ids)
            items = list(item_query.select_related(
                "question_version__question", "ministerial_exam_item__ministerial_exam"
            ).prefetch_related(
                "question_version__options",
                "question_version__stimulus_links__stimulus",
                "question_version__assets",
            ).order_by("sort_order"))
            if normalized_ids is not None:
                by_id = {str(item.id): item for item in items}
                if any(item_id not in by_id for item_id in normalized_ids):
                    raise ApplicationError(
                        "Assessment selection contains an unrelated question.",
                        code="INVALID_ASSESSMENT_SELECTION",
                    )
                items = [by_id[item_id] for item_id in normalized_ids]
        if not items:
            raise ApplicationError(
                "This assessment has no published questions.",
                code="NO_ASSESSMENT_QUESTIONS",
            )

        if q_shuffle:
            random.shuffle(items)

        # Calculate time expiration
        expires_at = None
        timing_mode = getattr(version, "timing_mode", "none")
        seconds_per_question = version.seconds_per_question
        if is_full_ministerial and timing_mode == "none":
            timing_mode = "calculated"
            seconds_per_question = getattr(settings, "ASSESSMENT_SECONDS_PER_QUESTION", 60)
        duration_seconds = None
        if timing_mode == "fixed" and version.duration_minutes:
            duration_seconds = version.duration_minutes * 60
        elif timing_mode == "calculated" and seconds_per_question:
            duration_seconds = seconds_per_question * len(items)
        elif version.duration_minutes and version.duration_minutes > 0:
            timing_mode = "fixed"
            duration_seconds = version.duration_minutes * 60
        if duration_seconds:
            expires_at = timezone.now() + timedelta(seconds=duration_seconds)

        attempt = AssessmentAttempt.objects.create(
            user=user,
            study_enrollment=enrollment,
            assessment=assessment,
            assessment_version=version,
            client_attempt_id=client_attempt_id,
            mode=mode,
            status=AttemptStatus.IN_PROGRESS,
            display_mode=version.default_display_mode,
            contract_version=1,
            source_scope=source_scope or {},
            feedback_policy=(
                "deferred"
                if is_full_ministerial
                else getattr(version, "feedback_policy", "deferred")
            ),
            timing_mode=timing_mode,
            duration_seconds=duration_seconds or 0,
            questions_shuffled=q_shuffle,
            options_shuffled=o_shuffle,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
        )

        total_max_score = Decimal("0.00")
        official_max_score = Decimal("0.00")
        attempt_questions = []

        for idx, item in enumerate(items, start=1):
            qv = item if direct_question_version_ids is not None else item.question_version
            item_points = qv.points if direct_question_version_ids is not None else item.points
            options = list(qv.options.all())
            is_reference = qv.question.question_type == "essay"
            if o_shuffle and qv.question.question_type != "true_false":
                random.shuffle(options)

            opt_order_keys = [opt.option_key for opt in options]

            meta = {}
            assessment_item = (
                None
                if direct_occurrence_ids is not None or direct_question_version_ids is not None
                else item
            )
            m_item = (
                item
                if direct_occurrence_ids is not None
                else None
                if direct_question_version_ids is not None
                else item.ministerial_exam_item
            )
            if m_item:
                m_exam = m_item.ministerial_exam
                meta = {
                    "year": m_exam.exam_year,
                    "exam_role": m_exam.exam_role,
                    "model_number": m_exam.model_number,
                    "question_number": m_item.question_number,
                    "ministerial_exam_id": str(m_exam.id),
                    "ministerial_exam_item_id": str(m_item.id),
                }
            elif direct_question_version_ids is not None:
                meta = dict(qv.question.metadata or {})

            # Build full immutable JSON snapshot
            q_snapshot = build_attempt_question_snapshot(
                question_version=qv,
                points=item_points,
                options=options,
                source_metadata=meta,
            )

            aq = AttemptQuestion(
                attempt=attempt,
                question_version=qv,
                assessment_item=assessment_item,
                ministerial_exam_item=m_item,
                source_type=qv.question.source_type if hasattr(qv, "question") else "ministerial",
                sort_order=idx,
                points=item_points,
                is_reference=is_reference,
                options_order_snapshot=opt_order_keys,
                source_metadata_snapshot=meta,
                question_snapshot=q_snapshot,
            )
            attempt_questions.append(aq)
            official_max_score += item_points
            if not is_reference:
                total_max_score += item_points

        AttemptQuestion.objects.bulk_create(attempt_questions)

        attempt.maximum_score = total_max_score
        attempt.official_maximum_score = official_max_score
        attempt.save(update_fields=["maximum_score", "official_maximum_score"])

        return attempt


def save_attempt_answer(
    *,
    attempt_id: str,
    attempt_question_id: str,
    user,
    answer_payload: dict | None = None,
    selected_option_id: str | None = None,
    selected_option_key: str | None = None,
    answer_text: str | None = None,
    is_flagged: bool = False,
    response_time_seconds: int = 0,
    client_revision: int = 0,
    expected_revision: int | None = None,
    expected_answer_revision: int | None = None,
    is_visited: bool = True,
    evaluate: bool = False,
    allow_expired_transport: bool = False,
    client_frozen_at=None,
) -> tuple[AttemptAnswer, dict]:
    expired_error = None
    with transaction.atomic():
        attempt = (
            AssessmentAttempt.objects.filter(id=attempt_id, user=user)
            .select_for_update()
            .first()
        )
        if not attempt:
            raise ApplicationError("المحاولة غير موجودة.", code="ATTEMPT_NOT_FOUND")
        if attempt.status in {
            AttemptStatus.SUBMITTED,
            AttemptStatus.EVALUATED,
            AttemptStatus.PENDING_REVIEW,
            AttemptStatus.EXPIRED,
        }:
            code = "ATTEMPT_EXPIRED" if attempt.status == AttemptStatus.EXPIRED else "ATTEMPT_FINALIZED"
            raise ApplicationError(
                "انتهت المحاولة ولا يمكن تعديلها.", code=code, status_code=409,
                fields={"status": attempt.status, "server_revision": attempt.revision},
            )
        if attempt.status not in {AttemptStatus.IN_PROGRESS, AttemptStatus.PAUSED}:
            raise ApplicationError(
                "انتقال حالة المحاولة غير صالح.", code="INVALID_TRANSITION", status_code=409,
                fields={"status": attempt.status, "server_revision": attempt.revision},
            )

        # Client timestamps are deliberately ignored. Without a trusted offline
        # attestation protocol, anything received after the server deadline is
        # rejected and the already accepted answers are finalized.
        if attempt.expires_at and timezone.now() >= attempt.expires_at:
            _finalize_locked_attempt(attempt, submission_reason="time_expired", expired=True)
            expired_error = ApplicationError(
                "انتهى الوقت المحدد للمحاولة.", code="ATTEMPT_EXPIRED", status_code=409,
                fields={"status": attempt.status, "server_revision": attempt.revision},
            )

        if expired_error is not None:
            # Leave the transaction normally so expiry finalization commits.
            answer = None
            response_data = None
        else:
            answer, response_data = _save_answer_on_locked_attempt(
                attempt=attempt,
                attempt_question_id=attempt_question_id,
                answer_payload=answer_payload,
                selected_option_id=selected_option_id,
                selected_option_key=selected_option_key,
                answer_text=answer_text,
                is_flagged=is_flagged,
                response_time_seconds=response_time_seconds,
                client_revision=client_revision,
                expected_revision=expected_revision,
                expected_answer_revision=expected_answer_revision,
                is_visited=is_visited,
                evaluate=evaluate,
            )

    if expired_error is not None:
        raise expired_error
    return answer, response_data


def _save_answer_on_locked_attempt(
    *, attempt, attempt_question_id, answer_payload, selected_option_id,
    selected_option_key, answer_text, is_flagged, response_time_seconds,
    client_revision, expected_revision, expected_answer_revision, is_visited,
    evaluate,
):
        if expected_revision is not None and expected_revision > attempt.revision:
            raise ApplicationError(
                "نسخة المحاولة غير متوافقة مع الخادم.", code="STALE_ATTEMPT", status_code=409,
                fields={"server_revision": attempt.revision, "status": attempt.status},
            )

        aq = AttemptQuestion.objects.filter(id=attempt_question_id, attempt=attempt).first()
        if not aq:
            raise ApplicationError("سؤال المحاولة غير موجود.", code="QUESTION_NOT_FOUND")

        # Prepare normalized answer_payload
        payload = copy.deepcopy(answer_payload or {})
        if selected_option_id and "selected_option_id" not in payload:
            payload["selected_option_id"] = str(selected_option_id)
        if selected_option_key and "selected_option_key" not in payload:
            payload["selected_option_key"] = str(selected_option_key)
        if answer_text and "text" not in payload:
            payload["text"] = answer_text
        sel_opt_id = payload.get("selected_option_id")
        sel_opt_key = payload.get("selected_option_key")

        # Validate selected option IDs belong to question snapshot
        snap_options = aq.question_snapshot.get("options", [])
        if snap_options:
            valid_opt_ids = {str(opt["id"]).lower() for opt in snap_options if "id" in opt}
            valid_opt_keys = {str(opt.get("option_key")) for opt in snap_options if opt.get("option_key")}
            if sel_opt_id and str(sel_opt_id).lower() not in valid_opt_ids:
                raise ApplicationError("الخيار المحدد لا ينتمي إلى هذا السؤال.", code="INVALID_OPTION")

            sel_opt_ids = payload.get("selected_option_ids", [])
            for opt_id in sel_opt_ids:
                if str(opt_id).lower() not in valid_opt_ids:
                    raise ApplicationError(f"الخيار {opt_id} لا ينتمي إلى هذا السؤال.", code="INVALID_OPTION")
            if sel_opt_key and str(sel_opt_key) not in valid_opt_keys:
                raise ApplicationError("Selected option key does not belong to this question.", code="INVALID_OPTION")
            for opt_key in payload.get("selected_option_keys", []):
                if str(opt_key) not in valid_opt_keys:
                    raise ApplicationError("Selected option key does not belong to this question.", code="INVALID_OPTION")
            if sel_opt_key and not sel_opt_id:
                matching = next((opt for opt in snap_options if str(opt.get("option_key")) == str(sel_opt_key)), None)
                sel_opt_id = matching.get("id") if matching else None
                payload["selected_option_id"] = sel_opt_id

        # The attempt row is already locked, so this answer read and write is
        # serialized only within the affected attempt.
        answer = AttemptAnswer.objects.filter(attempt=attempt, attempt_question=aq).first()
        current_answer_revision = answer.server_revision if answer else 0
        target_text = payload.get("text", answer_text)
        should_evaluate = (
            evaluate
            and attempt.mode == AttemptMode.PRACTICE
            and attempt.feedback_policy == "immediate"
            and not aq.is_reference
        )

        equivalent = bool(
            answer
            and answer.answer_payload == payload
            and answer.selected_option_key == sel_opt_key
            and str(answer.selected_option_id or "") == str(sel_opt_id or "")
            and (answer.answer_text or "") == (target_text or "")
            and answer.is_flagged == is_flagged
            and answer.is_visited == (is_visited or answer.is_visited)
            and (not should_evaluate or answer.is_evaluated)
        )

        if expected_answer_revision is not None and expected_answer_revision != current_answer_revision:
            if equivalent:
                return answer, _answer_response(attempt, aq, answer, should_evaluate, idempotent=True)
            raise ApplicationError(
                "تم تحديث هذه الإجابة من جهاز آخر.", code="ANSWER_CONFLICT", status_code=409,
                fields={
                    "server_revision": attempt.revision,
                    "answer_revision": current_answer_revision,
                    "status": attempt.status,
                    "server_answer": answer.answer_payload if answer else None,
                },
            )

        # Legacy callers without an explicit answer CAS token remain safe: an
        # update must advance their per-question client revision. New clients
        # always send expected_answer_revision.
        if answer and expected_answer_revision is None and client_revision <= answer.client_revision:
            if equivalent:
                return answer, _answer_response(attempt, aq, answer, should_evaluate, idempotent=True)
            raise ApplicationError(
                "يلزم تحديث حالة الإجابة قبل تعديلها.", code="ANSWER_CONFLICT", status_code=409,
                fields={
                    "server_revision": attempt.revision,
                    "answer_revision": answer.server_revision,
                    "status": attempt.status,
                    "server_answer": answer.answer_payload,
                },
            )

        if equivalent:
            return answer, _answer_response(
                attempt, aq, answer, should_evaluate, idempotent=True,
            )

        if not answer:
            answer = AttemptAnswer(
                attempt=attempt,
                attempt_question=aq,
                selected_option_id=sel_opt_id,
                selected_option_key=sel_opt_key,
                answer_text=payload.get("text", answer_text),
                answer_payload=payload,
                is_flagged=is_flagged,
                is_visited=is_visited,
                client_revision=client_revision,
                server_revision=1,
                response_time_seconds=response_time_seconds,
            )
        else:
            if answer.is_evaluated and (
                sel_opt_key != answer.selected_option_key
                or (sel_opt_id and str(sel_opt_id) != str(answer.selected_option_id))
            ):
                raise ApplicationError(
                    "An evaluated immediate answer is locked.",
                    code="ANSWER_LOCKED",
                )
            answer.selected_option_id = sel_opt_id
            answer.selected_option_key = sel_opt_key
            answer.answer_text = payload.get("text", answer_text)
            answer.answer_payload = payload
            answer.is_flagged = is_flagged
            answer.is_visited = is_visited or answer.is_visited
            answer.client_revision = max(client_revision, answer.client_revision)
            answer.server_revision += 1
            answer.response_time_seconds += response_time_seconds

        grading_result = grade_attempt_answer(
            question_snapshot=aq.question_snapshot,
            answer_payload=payload,
            max_points=aq.points,
        )

        if should_evaluate:
            answer.is_correct = grading_result["is_correct"]
            answer.awarded_points = grading_result["awarded_points"]
            answer.is_evaluated = True

        answer.save()

        # Update attempt counters
        answered_c = AttemptAnswer.objects.filter(attempt=attempt).exclude(
            selected_option_id__isnull=True, answer_text="", answer_payload={}
        ).count()
        attempt.answered_count = answered_c
        attempt.last_activity_at = timezone.now()
        attempt.revision += 1
        attempt.save(update_fields=["answered_count", "last_activity_at", "revision"])

        return answer, _answer_response(attempt, aq, answer, should_evaluate, grading_result=grading_result)


def _answer_response(attempt, aq, answer, should_evaluate, *, grading_result=None, idempotent=False):
        grading_result = grading_result or grade_attempt_answer(
            question_snapshot=aq.question_snapshot,
            answer_payload=answer.answer_payload or {},
            max_points=aq.points,
        )

        time_rem = None
        if attempt.expires_at:
            delta = (attempt.expires_at - timezone.now()).total_seconds()
            time_rem = max(0, int(delta))

        if should_evaluate:
            response_data = {
                "saved": True,
                "answered": True,
                "mode": attempt.mode,
                "is_correct": grading_result["is_correct"],
                "awarded_points": float(grading_result["awarded_points"]),
                "max_points": float(grading_result["max_points"]),
                "feedback_state": grading_result["feedback_state"],
                "selected_option_id": grading_result["selected_option_id"],
                "selected_option_ids": grading_result["selected_option_ids"],
                "correct_option_id": grading_result["correct_option_id"],
                "correct_option_ids": grading_result["correct_option_ids"],
                "correct_option_key": grading_result["correct_option_key"],
                "correct_option_keys": grading_result["correct_option_keys"],
                "correct_answer": grading_result["correct_answer"],
                "explanation": grading_result["explanation"],
                "time_remaining_seconds": time_rem,
                "server_revision": answer.server_revision,
                "answer_revision": answer.server_revision,
                "attempt_revision": attempt.revision,
                "server_time": timezone.now().isoformat(),
                "idempotent_replay": idempotent,
            }
        else:
            response_data = {
                "saved": True,
                "answered": True,
                "mode": attempt.mode,
                "answered_count": attempt.answered_count,
                "total_questions": attempt.attempt_questions.count(),
                "time_remaining_seconds": time_rem,
                "server_revision": answer.server_revision,
                "answer_revision": answer.server_revision,
                "attempt_revision": attempt.revision,
                "server_time": timezone.now().isoformat(),
                "idempotent_replay": idempotent,
                "feedback_state": "reference" if aq.is_reference else "saved",
            }

        return response_data


def submit_assessment_attempt(
    *, attempt_id: str, user, final_answers: list | None = None,
    submission_reason: str = "manual", final_frozen_at=None,
    expected_revision: int | None = None,
) -> AssessmentAttempt:
    with transaction.atomic():
        attempt = (
            AssessmentAttempt.objects.filter(id=attempt_id, user=user)
            .select_for_update()
            .first()
        )
        if not attempt:
            raise ApplicationError("المحاولة غير موجودة.", code="ATTEMPT_NOT_FOUND")

        if attempt.status in [AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED, AttemptStatus.PENDING_REVIEW]:
            return attempt
        if attempt.status == AttemptStatus.EXPIRED:
            if attempt.submitted_at is None:
                return _finalize_locked_attempt(attempt, submission_reason="time_expired", expired=True)
            return attempt
        if attempt.status not in {AttemptStatus.IN_PROGRESS, AttemptStatus.PAUSED}:
            raise ApplicationError(
                "انتقال حالة المحاولة غير صالح.", code="INVALID_TRANSITION", status_code=409,
                fields={"status": attempt.status, "server_revision": attempt.revision},
            )

        # The server receive time decides validity. final_frozen_at remains a
        # compatibility input only and never proves pre-deadline creation.
        if attempt.expires_at and timezone.now() >= attempt.expires_at:
            return _finalize_locked_attempt(attempt, submission_reason="time_expired", expired=True)

        if expected_revision is not None and expected_revision != attempt.revision and not final_answers:
            raise ApplicationError(
                "نسخة المحاولة قديمة.", code="STALE_ATTEMPT", status_code=409,
                fields={"server_revision": attempt.revision, "status": attempt.status},
            )

        for item in final_answers or []:
            save_attempt_answer(
                attempt_id=attempt_id,
                attempt_question_id=str(item.get("attempt_question_id", "")),
                user=user,
                answer_payload=item.get("answer") or {},
                selected_option_key=item.get("selected_option_key"),
                is_flagged=bool(item.get("is_flagged", False)),
                client_revision=int(item.get("client_revision", 0)),
                expected_revision=item.get("expected_revision", expected_revision),
                expected_answer_revision=item.get("expected_answer_revision"),
                is_visited=bool(item.get("is_visited", True)),
            )
        attempt.refresh_from_db()
        return _finalize_locked_attempt(
            attempt, submission_reason=submission_reason, expired=False,
        )


def _finalize_locked_attempt(attempt, *, submission_reason: str, expired: bool) -> AssessmentAttempt:
        attempt_questions = AttemptQuestion.objects.filter(attempt=attempt)
        answers = {ans.attempt_question_id: ans for ans in AttemptAnswer.objects.filter(attempt=attempt)}

        total_score = Decimal("0.00")
        correct_c = 0
        incorrect_c = 0
        unanswered_c = 0
        pending_review_c = 0

        for aq in attempt_questions:
            if aq.is_reference:
                # Essay/reference items remain visible with official points and
                # model answers, but are not interactive or auto-graded.
                continue
            ans = answers.get(aq.id)
            if not ans or (not ans.selected_option_id and not ans.answer_text and not ans.answer_payload):
                unanswered_c += 1
                if ans:
                    ans.is_correct = False
                    ans.awarded_points = Decimal("0.00")
                    ans.save()
                continue

            g_res = grade_attempt_answer(
                question_snapshot=aq.question_snapshot,
                answer_payload=ans.answer_payload or {"selected_option_id": ans.selected_option_id, "text": ans.answer_text},
                max_points=aq.points,
            )

            ans.is_correct = g_res["is_correct"]
            ans.awarded_points = g_res["awarded_points"]
            ans.is_evaluated = g_res["feedback_state"] != "pending_manual_review"
            ans.save(update_fields=["is_correct", "awarded_points", "is_evaluated", "updated_at"])

            if g_res["feedback_state"] == "pending_manual_review":
                pending_review_c += 1
            elif g_res["is_correct"] is True:
                correct_c += 1
                total_score += g_res["awarded_points"]
            elif g_res["is_correct"] is False:
                incorrect_c += 1

        if pending_review_c > 0:
            attempt.status = AttemptStatus.PENDING_REVIEW
        elif expired:
            attempt.status = AttemptStatus.EXPIRED
        else:
            attempt.status = AttemptStatus.EVALUATED

        attempt.submitted_at = timezone.now()
        attempt.frozen_at = attempt.expires_at if expired and attempt.expires_at else attempt.submitted_at
        attempt.submission_reason = submission_reason
        attempt.evaluated_at = timezone.now()
        attempt.answered_count = correct_c + incorrect_c + pending_review_c
        attempt.correct_count = correct_c
        attempt.incorrect_count = incorrect_c
        attempt.unanswered_count = unanswered_c
        attempt.pending_review_count = pending_review_c
        attempt.score = total_score
        attempt.revision += 1

        if attempt.maximum_score > 0:
            attempt.percentage = (total_score / attempt.maximum_score) * Decimal("100.00")
        else:
            attempt.percentage = Decimal("0.00")

        attempt.save()

        from apps.attempts.services.ar06_practice import project_attempt_evidence
        project_attempt_evidence(attempt)

        from apps.analytics.services.question_quality import project_attempt_question_quality
        project_attempt_question_quality(attempt)

        # Build analysis
        AttemptAnalysis.objects.update_or_create(
            attempt=attempt,
            defaults={
                "unit_breakdown": {"correct": correct_c, "incorrect": incorrect_c, "pending": pending_review_c},
                "lesson_breakdown": {},
                "difficulty_breakdown": {},
                "strengths": ["أداء ممتاز في الاختبار"] if attempt.percentage >= 70 else [],
                "weaknesses": ["مراجعة بعض الأسئلة الخاطئة"] if attempt.percentage < 70 else [],
                "recommendations": ["إعادة محاولة الأسئلة الخاطئة"],
            },
        )

        apply_attempt_submission_to_progress(attempt)

        return attempt


def get_authoritative_attempt(*, attempt_id: str, user) -> AssessmentAttempt | None:
    """Load current state and reconcile a deadline that elapsed between requests."""
    with transaction.atomic():
        attempt = (
            AssessmentAttempt.objects.select_for_update()
            .filter(id=attempt_id, user=user)
            .first()
        )
        if not check_attempt_snapshot_access(user=user, attempt=attempt).allowed:
            return None
        if (
            attempt
            and attempt.status in {AttemptStatus.IN_PROGRESS, AttemptStatus.PAUSED}
            and attempt.expires_at
            and timezone.now() >= attempt.expires_at
        ):
            attempt = _finalize_locked_attempt(
                attempt, submission_reason="time_expired", expired=True,
            )
        return attempt


def get_attempt_review(*, attempt_id: str, user) -> dict:
    attempt = AssessmentAttempt.objects.filter(id=attempt_id, user=user).select_related("assessment").first()
    if not attempt:
        raise ApplicationError("المحاولة غير موجودة.", code="ATTEMPT_NOT_FOUND")

    if attempt.mode == AttemptMode.EXAM and attempt.status not in [
        AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED, AttemptStatus.PENDING_REVIEW, AttemptStatus.EXPIRED
    ]:
        raise ApplicationError("مراجعة المحاولة غير متاحة قبل التسليم.", code="REVIEW_NOT_ALLOWED")

    questions = AttemptQuestion.objects.filter(attempt=attempt).order_by("sort_order")
    answers = {ans.attempt_question_id: ans for ans in AttemptAnswer.objects.filter(attempt=attempt)}

    items_review = []
    for aq in questions:
        ans = answers.get(aq.id)
        payload = ans.answer_payload if ans else {}
        g_res = grade_attempt_answer(
            question_snapshot=aq.question_snapshot,
            answer_payload=payload,
            max_points=aq.points,
        )
        if aq.is_reference:
            g_res.update(
                is_correct=None,
                awarded_points=Decimal("0.00"),
                feedback_state="reference",
                correct_answer=aq.question_snapshot.get("model_answer"),
            )

        items_review.append({
            "attempt_question_id": str(aq.id),
            "sort_order": aq.sort_order,
            "points": float(aq.points),
            "question_type": aq.question_snapshot.get("question_type", "multiple_choice"),
            "is_reference": aq.is_reference,
            "model_answer": aq.question_snapshot.get("model_answer") if aq.is_reference else None,
            "question_text": aq.question_snapshot.get("question_text", ""),
            "prompt_layout": aq.question_snapshot.get("prompt_layout", "vertical"),
            "options": aq.question_snapshot.get("options", []),
            "stimuli": aq.question_snapshot.get("stimuli", []),
            "assets": aq.question_snapshot.get("assets", []),
            "student_answer": payload,
            "is_flagged": ans.is_flagged if ans else False,
            "is_correct": g_res["is_correct"],
            "awarded_points": float(g_res["awarded_points"]),
            "feedback_state": g_res["feedback_state"],
            "correct_option_id": g_res["correct_option_id"],
            "correct_option_ids": g_res["correct_option_ids"],
            "correct_option_key": g_res["correct_option_key"],
            "correct_option_keys": g_res["correct_option_keys"],
            "correct_answer": g_res["correct_answer"],
            "explanation": g_res["explanation"],
            "source_metadata": aq.source_metadata_snapshot,
        })

    return {
        "attempt_id": str(attempt.id),
        "assessment_title": attempt.assessment_title,
        "mode": attempt.mode,
        "status": attempt.status,
        "score": float(attempt.score),
        "maximum_score": float(attempt.maximum_score),
        "official_maximum_score": float(attempt.official_maximum_score),
        "percentage": float(attempt.percentage),
        "answered_count": attempt.answered_count,
        "correct_count": attempt.correct_count,
        "incorrect_count": attempt.incorrect_count,
        "unanswered_count": attempt.unanswered_count,
        "pending_review_count": attempt.pending_review_count,
        "submitted_at": attempt.submitted_at,
        "questions": items_review,
    }


def create_wrong_answers_attempt(*, parent_attempt_id: str, user) -> AssessmentAttempt:
    from apps.attempts.services.ar06_practice import create_per_attempt_wrong_practice

    return create_per_attempt_wrong_practice(
        parent_attempt_id=parent_attempt_id, user=user,
    )


def create_retry_attempt(*, parent_attempt_id: str, user) -> AssessmentAttempt:
    """Retry the same logical set; dynamic practice sources receive a fresh order."""
    with transaction.atomic():
        parent = (
            AssessmentAttempt.objects.select_for_update(of=("self",))
            .select_related("assessment", "study_enrollment")
            .filter(id=parent_attempt_id, user=user)
            .first()
        )
        if not parent or parent.status not in [
            AttemptStatus.SUBMITTED,
            AttemptStatus.EVALUATED,
            AttemptStatus.PENDING_REVIEW,
            AttemptStatus.EXPIRED,
        ]:
            raise ApplicationError(
                "The source attempt is not complete or was not found.",
                code="PARENT_ATTEMPT_INVALID",
            )

        enrollment = StudyEnrollment.objects.filter(
            id=parent.study_enrollment_id, user=user, is_active=True
        ).first()
        if enrollment is None:
            raise ApplicationError(
                "The assessment is no longer available.",
                code="ASSESSMENT_NOT_FOUND",
            )
        if parent.assessment_id:
            if parent.assessment.status != "published":
                raise ApplicationError(
                    "The assessment is no longer available.", code="ASSESSMENT_NOT_FOUND",
                )
            from apps.entitlements.services.access_service import check_resource_access
            decision = check_resource_access(
                user=user, enrollment=enrollment, resource_type="assessment",
                resource_id=str(parent.assessment_id),
            )
            if not decision.allowed:
                raise ApplicationError(
                    "This assessment is not available under the current subscription.",
                    code="SUBSCRIPTION_REQUIRED",
                )
        elif parent.dynamic_assessment_type in {
            AssessmentType.CUSTOM_TEST,
            AssessmentType.MOCK_EXAM,
        }:
            from apps.attempts.services.selection_engine import SelectionEngine, normalize_selection_spec
            SelectionEngine(
                user=user, enrollment=enrollment,
                spec=normalize_selection_spec(parent.selection_spec_snapshot),
                generation_mode=(
                    "mock" if parent.dynamic_assessment_type == AssessmentType.MOCK_EXAM
                    else "custom"
                ),
            )
        elif parent.dynamic_assessment_type in {
            AssessmentType.WRONG_ANSWERS_TEST,
            "weakness_practice",
        }:
            from apps.attempts.services.ar06_practice import _assert_question_access

            _assert_question_access(
                user=user,
                enrollment=enrollment,
                questions=list(
                    parent.attempt_questions.select_related(
                        "question_version__question__subject"
                    )
                ),
            )
        else:
            raise ApplicationError(
                "The dynamic assessment identity is invalid.", code="ASSESSMENT_NOT_FOUND",
            )

        retry_attempt_type = (
            AttemptType.WRONG_ANSWERS
            if parent.dynamic_assessment_type == AssessmentType.WRONG_ANSWERS_TEST
            else AttemptType.RETRY_FULL
        )
        existing = AssessmentAttempt.objects.filter(
            parent_attempt=parent,
            user=user,
            attempt_type=retry_attempt_type,
            status__in=[
                AttemptStatus.CREATED,
                AttemptStatus.IN_PROGRESS,
                AttemptStatus.PAUSED,
            ],
        ).order_by("-created_at").first()
        if existing is not None:
            return existing

        original_questions = list(
            AttemptQuestion.objects.filter(attempt=parent).order_by("sort_order")
        )
        if not original_questions:
            raise ApplicationError(
                "The source attempt has no questions.",
                code="NO_ASSESSMENT_QUESTIONS",
            )
        dynamic_shuffle = (parent.source_scope or {}).get("kind") in {
            "lesson_training",
            "unit_training",
            "subject_training",
            "lesson_ministerial",
            "unit_ministerial",
            "custom_test",
            "mock_exam",
            "wrong_answers_test",
            "weakness_practice",
        }
        if dynamic_shuffle:
            random.shuffle(original_questions)
        expires_at = (
            timezone.now() + timedelta(seconds=parent.duration_seconds)
            if parent.duration_seconds
            else None
        )
        retry = AssessmentAttempt.objects.create(
            user=user,
            study_enrollment=enrollment,
            assessment=parent.assessment,
            assessment_version=parent.assessment_version,
            blueprint=parent.blueprint,
            dynamic_assessment_type=parent.dynamic_assessment_type,
            dynamic_title=parent.dynamic_title,
            dynamic_subject=parent.dynamic_subject,
            selection_spec_snapshot=parent.selection_spec_snapshot,
            selection_policy_snapshot={
                **(parent.selection_policy_snapshot or {}),
                "retry_of_attempt_id": str(parent.id),
            },
            parent_attempt=parent,
            attempt_type=retry_attempt_type,
            mode=parent.mode,
            status=AttemptStatus.IN_PROGRESS,
            display_mode=parent.display_mode,
            contract_version=parent.contract_version,
            source_scope=parent.source_scope,
            feedback_policy=parent.feedback_policy,
            timing_mode=parent.timing_mode,
            duration_seconds=parent.duration_seconds,
            questions_shuffled=dynamic_shuffle or parent.questions_shuffled,
            options_shuffled=dynamic_shuffle or parent.options_shuffled,
            expires_at=expires_at,
        )
        retry_questions = []
        for index, question in enumerate(original_questions, 1):
            snapshot = copy.deepcopy(question.question_snapshot)
            options = list(snapshot.get("options") or [])
            if dynamic_shuffle and snapshot.get("question_type") != "true_false":
                random.shuffle(options)
                snapshot["options"] = options
            option_keys = [str(option.get("option_key", "")) for option in options]
            retry_questions.append(AttemptQuestion(
                attempt=retry,
                question_version=question.question_version,
                assessment_item=question.assessment_item,
                ministerial_exam_item=question.ministerial_exam_item,
                source_type=question.source_type,
                sort_order=index,
                points=question.points,
                is_reference=question.is_reference,
                options_order_snapshot=(
                    option_keys if dynamic_shuffle else question.options_order_snapshot
                ),
                source_metadata_snapshot=question.source_metadata_snapshot,
                question_snapshot=snapshot,
            ))
        AttemptQuestion.objects.bulk_create(retry_questions)
        retry.maximum_score = parent.maximum_score
        retry.official_maximum_score = parent.official_maximum_score
        retry.save(update_fields=["maximum_score", "official_maximum_score"])
        return retry
