import logging
from decimal import Decimal
from apps.attempts.models import AssessmentAttempt, AttemptStatus, AttemptType
from apps.progress.models import (
    AttemptProgressReceipt, LearningResourceProgress, LessonProgress, UnitProgress, SubjectProgress, ProgressStatus
)
from apps.progress.services.recalculation import (
    recalculate_lesson_progress, recalculate_unit_progress, recalculate_subject_progress
)

logger = logging.getLogger("progress.attempt_integration")

def apply_attempt_submission_to_progress(attempt: AssessmentAttempt):
    """
    Called after attempt is finalized (submitted/evaluated).
    Idempotent. Updates Progress records.
    """
    if attempt.status not in [AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED]:
        return

    # Check Receipt
    receipt, created = AttemptProgressReceipt.objects.get_or_create(attempt=attempt)
    if not created:
        logger.info(f"Attempt {attempt.id} already processed for progress.")
        return receipt

    # AR-06 historical mistake practice never re-completes the original
    # assessment or mutates its FE-05 score aggregates.
    if attempt.attempt_type == AttemptType.WRONG_ANSWERS:
        return receipt

    # Dynamic custom tests contribute through their underlying Training and
    # Ministerial AttemptQuestion provenance.  They intentionally do not mark
    # curriculum content or a synthetic assessment resource as completed.
    if attempt.assessment_id is None:
        return receipt

    # Mark corresponding learning resource as completed for the assessment
    res_progress, _ = LearningResourceProgress.objects.get_or_create(
        user=attempt.user,
        study_enrollment=attempt.study_enrollment,
        resource_type="assessment",
        resource_id=str(attempt.assessment_id),
        defaults={
            "subject_id": attempt.assessment.subject_id,
            "unit_id": attempt.assessment.unit_id,
            "lesson_id": attempt.assessment.lesson_id,
            "status": ProgressStatus.COMPLETED,
            "completion_percentage": 100.0,
            "started_at": attempt.created_at,
            "completed_at": attempt.submitted_at,
            "time_spent_seconds": 0,
        }
    )
    if res_progress.status != ProgressStatus.COMPLETED:
        res_progress.status = ProgressStatus.COMPLETED
        res_progress.completion_percentage = 100.0
        res_progress.completed_at = attempt.submitted_at
        res_progress.save(update_fields=["status", "completion_percentage", "completed_at", "updated_at"])

    # Attempt score info
    score_pct = Decimal(str(attempt.percentage))
    
    # Depending on assessment location, update Lesson, Unit or Subject
    if attempt.assessment.lesson_id:
        lp, _ = LessonProgress.objects.get_or_create(
            user=attempt.user,
            study_enrollment=attempt.study_enrollment,
            lesson_id=attempt.assessment.lesson_id
        )
        
        lp.attempts_count += 1
        lp.latest_score = score_pct
        if score_pct > lp.best_score:
            lp.best_score = score_pct
        
        # simple moving average for average_score
        lp.average_score = ((Decimal(str(lp.average_score)) * (lp.attempts_count - 1)) + score_pct) / lp.attempts_count
        
        # FE-05 keeps assessment performance separate from mastery. A future
        # explicit mastery policy may update mastery_percentage; best score is
        # not a mastery algorithm.
        lp.save()
        
        # Recalculate component completion
        recalculate_lesson_progress(user=attempt.user, enrollment=attempt.study_enrollment, lesson_id=str(attempt.assessment.lesson_id))

    if attempt.assessment.unit_id:
        up, _ = UnitProgress.objects.get_or_create(
            user=attempt.user,
            study_enrollment=attempt.study_enrollment,
            unit_id=attempt.assessment.unit_id
        )
        up.attempts_count += 1
        up.latest_score = score_pct
        if score_pct > up.best_score:
            up.best_score = score_pct
            
        up.average_score = ((Decimal(str(up.average_score)) * (up.attempts_count - 1)) + score_pct) / up.attempts_count
        up.save()
        
        recalculate_unit_progress(user=attempt.user, enrollment=attempt.study_enrollment, unit_id=str(attempt.assessment.unit_id), recalculate_parent=False)

    if attempt.assessment.subject_id:
        sp, _ = SubjectProgress.objects.get_or_create(
            user=attempt.user,
            study_enrollment=attempt.study_enrollment,
            subject_id=attempt.assessment.subject_id
        )
        sp.attempts_count += 1
        sp.latest_score = score_pct
        if score_pct > sp.best_score:
            sp.best_score = score_pct
            
        sp.average_score = ((Decimal(str(sp.average_score)) * (sp.attempts_count - 1)) + score_pct) / sp.attempts_count
        sp.save()
        
        recalculate_subject_progress(user=attempt.user, enrollment=attempt.study_enrollment, subject_id=str(attempt.assessment.subject_id))

    return receipt
