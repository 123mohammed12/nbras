import logging
from django.db import transaction
from django.utils import timezone
from apps.accounts.models import User
from apps.progress.models import (
    LearningResourceProgress, LearningSession, LessonProgress, UnitProgress, SubjectProgress
)
from apps.progress.services.recalculation import (
    recalculate_lesson_progress, recalculate_unit_progress, recalculate_subject_progress
)

logger = logging.getLogger("progress.guest_merge")


def progress_merge_handler(source_guest: User, target_user: User) -> dict:
    """
    Merge handler for moving Progress records from guest to authenticated user.
    """
    stats = {
        "learning_resources_moved": 0,
        "sessions_moved": 0,
        "conflicts_resolved": 0
    }
    
    with transaction.atomic():
        # Move sessions safely
        sessions = LearningSession.objects.filter(user=source_guest)
        for s in sessions:
            exists = LearningSession.objects.filter(
                user=target_user, client_session_id=s.client_session_id
            ).exists()
            if not exists:
                s.user = target_user
                s.save(update_fields=["user", "updated_at"])
                stats["sessions_moved"] += 1
                
        # Move resources safely
        resources = LearningResourceProgress.objects.filter(user=source_guest)
        subjects_to_recalc = set()
        
        for r in resources:
            target_r = LearningResourceProgress.objects.filter(
                user=target_user, 
                study_enrollment=r.study_enrollment,
                resource_type=r.resource_type,
                resource_id=r.resource_id
            ).first()
            
            if target_r:
                # Merge logic
                if r.completion_percentage > target_r.completion_percentage:
                    target_r.completion_percentage = r.completion_percentage
                    target_r.status = r.status
                    target_r.completed_at = r.completed_at
                
                target_r.time_spent_seconds += r.time_spent_seconds
                if target_r.started_at and r.started_at and r.started_at < target_r.started_at:
                    target_r.started_at = r.started_at
                    
                target_r.save()
                r.delete()
                stats["conflicts_resolved"] += 1
            else:
                r.user = target_user
                r.save(update_fields=["user", "updated_at"])
                stats["learning_resources_moved"] += 1
                
            if r.subject_id:
                subjects_to_recalc.add((r.study_enrollment_id, r.subject_id))
                
        # Move pre-calculated progress? It's better to just recalculate everything for the target user
        LessonProgress.objects.filter(user=source_guest).delete()
        UnitProgress.objects.filter(user=source_guest).delete()
        SubjectProgress.objects.filter(user=source_guest).delete()
        
        # Recalculate
        for enrollment_id, subj_id in subjects_to_recalc:
            from apps.curriculum.models import StudyEnrollment
            enrollment = StudyEnrollment.objects.filter(id=enrollment_id).first()
            if enrollment:
                recalculate_subject_progress(user=target_user, enrollment=enrollment, subject_id=subj_id)
                
    return stats
