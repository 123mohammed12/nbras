import logging
from decimal import Decimal
from django.utils import timezone
from apps.curriculum.models import Lesson, Unit, Subject
from apps.content.models import LessonExplanation
from apps.progress.models import (
    LearningResourceProgress, LessonProgress, UnitProgress, SubjectProgress, ProgressStatus
)

logger = logging.getLogger("progress.recalculation")

def get_required_resources_for_lesson(lesson_id: str) -> list[dict]:
    # Lesson completion is content completion. Summaries, cards and assessments
    # have their own progress/mastery and must not complete the lesson.
    exps = list(LessonExplanation.objects.filter(lesson_id=lesson_id, status="published").values_list("id", flat=True))
    return [{"type": "lesson_explanation", "id": str(pid)} for pid in exps]

def compute_lesson_accessible_completion(*, user, enrollment, lesson_id: str, context=None) -> float:
    from apps.entitlements.services.access_service import check_resources_access_batch, AccessContext
    req_res = get_required_resources_for_lesson(lesson_id)
    if not req_res:
        return 0.0

    if not context:
        context = AccessContext.build(user=user, enrollment=enrollment)

    access_map = check_resources_access_batch(user=user, enrollment=enrollment, resources=req_res, context=context)
    accessible_res = [r for r in req_res if access_map.get((r["type"], str(r["id"]))) and access_map[(r["type"], str(r["id"]))].allowed]

    if not accessible_res:
        return 0.0

    completed_ids = set(
        LearningResourceProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            completion_percentage__gte=100,
            resource_id__in=[r["id"] for r in accessible_res],
        ).values_list("resource_id", flat=True)
    )

    completed_count = len(completed_ids)
    return round((completed_count / len(accessible_res)) * 100.0, 2)


def compute_unit_accessible_completion(*, user, enrollment, unit_id: str, context=None) -> float:
    from apps.entitlements.services.access_service import check_resources_access_batch, AccessContext
    unit = Unit.objects.filter(id=unit_id, status="published").first()
    if not unit:
        return 0.0

    if not context:
        context = AccessContext.build(user=user, enrollment=enrollment)

    lessons = list(Lesson.objects.filter(unit_id=unit_id, status="published"))
    res_to_check = [{"type": "lesson", "id": str(l.id)} for l in lessons]

    access_map = check_resources_access_batch(user=user, enrollment=enrollment, resources=res_to_check, context=context)

    accessible_lessons = [l for l in lessons if access_map.get(("lesson", str(l.id))) and access_map[("lesson", str(l.id))].allowed]
    total_accessible = len(accessible_lessons)
    if total_accessible == 0:
        return 0.0

    # Bulk fetch required resources for all accessible lessons in 4 queries
    les_ids = [str(l.id) for l in accessible_lessons]
    exps = list(LessonExplanation.objects.filter(lesson_id__in=les_ids, status="published").values("id", "lesson_id"))

    lesson_res_map = {lid: [] for lid in les_ids}
    all_lesson_res = []
    for r in exps:
        res_item = {"type": "lesson_explanation", "id": str(r["id"])}
        lesson_res_map[str(r["lesson_id"])].append(res_item)
        all_lesson_res.append(res_item)
    lesson_res_access_map = check_resources_access_batch(user=user, enrollment=enrollment, resources=all_lesson_res, context=context)

    all_res_ids = [r["id"] for r in all_lesson_res]
    completed_ids = set(
        LearningResourceProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            completion_percentage__gte=100,
            resource_id__in=all_res_ids,
        ).values_list("resource_id", flat=True)
    )

    comp_pcts = []
    for l in accessible_lessons:
        reqs = lesson_res_map.get(str(l.id), [])
        acc_reqs = [r for r in reqs if lesson_res_access_map.get((r["type"], r["id"])) and lesson_res_access_map[(r["type"], r["id"])].allowed]
        if not acc_reqs:
            comp_pcts.append(0.0)
        else:
            c_cnt = sum(1 for r in acc_reqs if r["id"] in completed_ids)
            comp_pcts.append(round((c_cnt / len(acc_reqs)) * 100.0, 2))

    return round(sum(comp_pcts) / total_accessible, 2)


def compute_subject_accessible_completion(*, user, enrollment, subject_id: str, context=None) -> float:
    from apps.progress.services.progress_selectors import calculate_accessible_completion_for_subjects
    subject = Subject.objects.filter(id=subject_id, status="published").first()
    if not subject:
        return 0.0
    res_map = calculate_accessible_completion_for_subjects(user, enrollment, [subject], context=context)
    return res_map.get(str(subject_id), 0.0)




def recalculate_lesson_progress(*, user, enrollment, lesson_id: str) -> LessonProgress:
    lesson = Lesson.objects.filter(id=lesson_id, status="published").first()
    if not lesson:
        return None
        
    req_res = get_required_resources_for_lesson(lesson_id)
    total_req = len(req_res)
    
    lp, _ = LessonProgress.objects.get_or_create(
        user=user, study_enrollment=enrollment, lesson=lesson
    )
    
    if total_req == 0:
        lp.completion_percentage = Decimal("0.00")
        lp.status = ProgressStatus.NOT_STARTED
        lp.save(update_fields=["completion_percentage", "status", "updated_at"])
        return lp
        
    completed_ids = set(
        LearningResourceProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            completion_percentage__gte=100,
            resource_id__in=[r["id"] for r in req_res],
        ).values_list("resource_id", flat=True)
    )
    completed_count = len(completed_ids)
            
    pct = (completed_count / total_req) * 100.0
    lp.completion_percentage = Decimal(f"{pct:.2f}")
    
    if pct >= 100.0:
        lp.status = ProgressStatus.COMPLETED
        if not lp.completed_at:
            lp.completed_at = timezone.now()
    elif pct > 0:
        lp.status = ProgressStatus.IN_PROGRESS
        lp.completed_at = None
    else:
        lp.status = ProgressStatus.NOT_STARTED
        lp.completed_at = None
        
    # Completion status is content-owned. FE-05 intentionally does not derive
    # mastery or a needs-review completion state from assessment scores.
    lp.save()
    return lp


def recalculate_unit_progress(*, user, enrollment, unit_id: str, recalculate_parent: bool = True) -> UnitProgress:
    unit = Unit.objects.filter(id=unit_id, status="published").first()
    if not unit:
        return None
        
    lessons = list(Lesson.objects.filter(unit_id=unit_id, status="published"))
    existing_lps = {
        str(lp.lesson_id): lp
        for lp in LessonProgress.objects.filter(user=user, study_enrollment=enrollment, lesson__in=lessons)
    }

    lesson_pcts = []
    for l in lessons:
        lp = existing_lps.get(str(l.id))
        if not lp:
            lp = recalculate_lesson_progress(user=user, enrollment=enrollment, lesson_id=str(l.id))
        lesson_pcts.append(float(lp.completion_percentage) if lp else 0.0)
        
    total_components = len(lesson_pcts)
    
    up, _ = UnitProgress.objects.get_or_create(
        user=user, study_enrollment=enrollment, unit=unit
    )
    
    if total_components == 0:
        up.completion_percentage = Decimal("0.00")
        up.lessons_completed = 0
        up.lessons_total = 0
        up.status = ProgressStatus.NOT_STARTED
        up.save()
        return up
        
    total_pct = sum(lesson_pcts)
    up.lessons_total = len(lesson_pcts)
    up.lessons_completed = len([p for p in lesson_pcts if p >= 100.0])
    
    pct = total_pct / total_components
    up.completion_percentage = Decimal(f"{pct:.2f}")
    
    if pct >= 100.0:
        up.status = ProgressStatus.COMPLETED
        if not up.completed_at:
            up.completed_at = timezone.now()
    elif pct > 0:
        up.status = ProgressStatus.IN_PROGRESS
        up.completed_at = None
    else:
        up.status = ProgressStatus.NOT_STARTED
        up.completed_at = None
        
    up.save()
    if recalculate_parent:
        recalculate_subject_progress(user=user, enrollment=enrollment, subject_id=str(unit.subject_id))
    return up


def recalculate_subject_progress(*, user, enrollment, subject_id: str) -> SubjectProgress:
    subject = Subject.objects.filter(id=subject_id, status="published").first()
    if not subject:
        return None
        
    units = list(Unit.objects.filter(subject_id=subject_id, status="published"))
    
    sp, _ = SubjectProgress.objects.get_or_create(
        user=user, study_enrollment=enrollment, subject=subject
    )
    
    if len(units) == 0:
        sp.completion_percentage = Decimal("0.00")
        sp.units_completed = 0
        sp.units_total = 0
        sp.status = ProgressStatus.NOT_STARTED
        sp.save()
        return sp

    existing_ups = {
        str(up.unit_id): up
        for up in UnitProgress.objects.filter(user=user, study_enrollment=enrollment, unit__in=units)
    }

    unit_pcts = [float(existing_ups[str(u.id)].completion_percentage) if str(u.id) in existing_ups else 0.0 for u in units]
        
    total_pct = sum(unit_pcts)
    sp.units_total = len(unit_pcts)
    sp.units_completed = len([p for p in unit_pcts if p >= 100.0])
    
    pct = total_pct / len(units)
    sp.completion_percentage = Decimal(f"{pct:.2f}")
    
    if pct >= 100.0:
        sp.status = ProgressStatus.COMPLETED
        if not sp.completed_at:
            sp.completed_at = timezone.now()
    elif pct > 0:
        sp.status = ProgressStatus.IN_PROGRESS
        sp.completed_at = None
    else:
        sp.status = ProgressStatus.NOT_STARTED
        sp.completed_at = None
        
    sp.save()
    return sp
