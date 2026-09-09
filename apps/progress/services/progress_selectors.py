from apps.entitlements.services.access_service import AccessContext, check_resources_access_batch
from apps.progress.models import SubjectProgress, LearningResourceProgress
from apps.curriculum.models import Subject, Unit, Lesson
from apps.content.models import LessonExplanation


def calculate_accessible_completion_for_lessons(user, enrollment, lessons, context=None) -> dict[str, float]:
    if not lessons or not user or not enrollment:
        return {}
    context = context or AccessContext.build(user=user, enrollment=enrollment)
    lesson_ids = [str(lesson.id) for lesson in lessons]
    lesson_access = check_resources_access_batch(
        user=user,
        enrollment=enrollment,
        resources=[{"type": "lesson", "id": lesson_id} for lesson_id in lesson_ids],
        context=context,
    )
    explanations = list(
        LessonExplanation.objects.filter(
            lesson_id__in=lesson_ids, status="published"
        ).values("id", "lesson_id")
    )
    explanation_by_lesson = {
        str(item["lesson_id"]): str(item["id"]) for item in explanations
    }
    explanation_access = check_resources_access_batch(
        user=user,
        enrollment=enrollment,
        resources=[{"type": "lesson_explanation", "id": str(item["id"])} for item in explanations],
        context=context,
    )
    completed_ids = set(
        LearningResourceProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            resource_type="lesson_explanation",
            resource_id__in=list(explanation_by_lesson.values()),
            completion_percentage__gte=100,
        ).values_list("resource_id", flat=True)
    )
    result = {}
    for lesson_id in lesson_ids:
        lesson_decision = lesson_access.get(("lesson", lesson_id))
        explanation_id = explanation_by_lesson.get(lesson_id)
        explanation_decision = explanation_access.get(("lesson_explanation", explanation_id)) if explanation_id else None
        if not lesson_decision or not lesson_decision.allowed or not explanation_id or not explanation_decision or not explanation_decision.allowed:
            result[lesson_id] = 0.0
        else:
            result[lesson_id] = 100.0 if explanation_id in completed_ids else 0.0
    return result


def calculate_accessible_completion_for_units(user, enrollment, units, context=None) -> dict[str, float]:
    if not units or not user or not enrollment:
        return {}
    context = context or AccessContext.build(user=user, enrollment=enrollment)
    unit_ids = [str(unit.id) for unit in units]
    unit_access = check_resources_access_batch(
        user=user,
        enrollment=enrollment,
        resources=[{"type": "unit", "id": unit_id} for unit_id in unit_ids],
        context=context,
    )
    lessons = list(Lesson.objects.filter(unit_id__in=unit_ids, status="published"))
    lesson_percentages = calculate_accessible_completion_for_lessons(
        user, enrollment, lessons, context=context
    )
    lessons_by_unit = {unit_id: [] for unit_id in unit_ids}
    for lesson in lessons:
        lessons_by_unit[str(lesson.unit_id)].append(str(lesson.id))
    result = {}
    for unit_id in unit_ids:
        decision = unit_access.get(("unit", unit_id))
        child_ids = lessons_by_unit.get(unit_id, [])
        if not decision or not decision.allowed or not child_ids:
            result[unit_id] = 0.0
        else:
            result[unit_id] = round(
                sum(lesson_percentages.get(lesson_id, 0.0) for lesson_id in child_ids)
                / len(child_ids),
                2,
            )
    return result


def calculate_accessible_completion_for_subjects(user, enrollment, subjects, context=None) -> dict[str, float]:
    """
    Computes accessible_completion_percentage for a list of Subject objects in bulk queries.
    Returns map {str(subject_id): float_percentage}.
    """
    if not subjects or not user or not enrollment:
        return {}

    if not context:
        context = AccessContext.build(user=user, enrollment=enrollment)

    subj_ids = [str(s.id) for s in subjects]

    # 1. Fetch units
    units = list(Unit.objects.filter(subject_id__in=subj_ids, status="published").select_related("subject"))
    if not units:
        return {sid: 0.0 for sid in subj_ids}

    unit_res = [{"type": "unit", "id": str(u.id)} for u in units]
    unit_access_map = check_resources_access_batch(user=user, enrollment=enrollment, resources=unit_res, context=context)

    accessible_units = [u for u in units if unit_access_map.get(("unit", str(u.id))) and unit_access_map[("unit", str(u.id))].allowed]
    if not accessible_units:
        return {sid: 0.0 for sid in subj_ids}

    acc_unit_ids = [str(u.id) for u in accessible_units]
    subj_acc_units = {sid: [] for sid in subj_ids}
    for u in accessible_units:
        subj_acc_units[str(u.subject_id)].append(u)

    # 2. Fetch lessons. Assessments affect mastery, not content completion.
    lessons = list(Lesson.objects.filter(unit_id__in=acc_unit_ids, status="published").select_related("unit"))
    component_res = [{"type": "lesson", "id": str(l.id)} for l in lessons]
    comp_access_map = check_resources_access_batch(user=user, enrollment=enrollment, resources=component_res, context=context)

    accessible_lessons = [l for l in lessons if comp_access_map.get(("lesson", str(l.id))) and comp_access_map[("lesson", str(l.id))].allowed]

    unit_acc_lessons = {uid: [] for uid in acc_unit_ids}
    for l in accessible_lessons:
        unit_acc_lessons[str(l.unit_id)].append(l)

    # 3. Fetch required resources for accessible lessons
    acc_les_ids = [str(l.id) for l in accessible_lessons]
    exps = list(LessonExplanation.objects.filter(lesson_id__in=acc_les_ids, status="published").values("id", "lesson_id"))

    lesson_res_map = {lid: [] for lid in acc_les_ids}
    all_lesson_res = []
    for r in exps:
        item = {"type": "lesson_explanation", "id": str(r["id"])}
        lesson_res_map[str(r["lesson_id"])].append(item)
        all_lesson_res.append(item)
    lesson_res_access = check_resources_access_batch(user=user, enrollment=enrollment, resources=all_lesson_res, context=context)

    # 4. Fetch LearningResourceProgress
    all_target_ids = [r["id"] for r in all_lesson_res]
    completed_ids = set(
        LearningResourceProgress.objects.filter(
            user=user,
            study_enrollment=enrollment,
            completion_percentage__gte=100,
            resource_id__in=all_target_ids,
        ).values_list("resource_id", flat=True)
    )

    # In memory calculation
    unit_pct_map = {}
    for uid in acc_unit_ids:
        acc_les = unit_acc_lessons.get(uid, [])
        total_comp = len(acc_les)
        if total_comp == 0:
            unit_pct_map[uid] = 0.0
            continue

        comp_pcts = []
        for l in acc_les:
            reqs = lesson_res_map.get(str(l.id), [])
            acc_reqs = [r for r in reqs if lesson_res_access.get((r["type"], r["id"])) and lesson_res_access[(r["type"], r["id"])].allowed]
            if not acc_reqs:
                comp_pcts.append(0.0)
            else:
                c_cnt = sum(1 for r in acc_reqs if r["id"] in completed_ids)
                comp_pcts.append(round((c_cnt / len(acc_reqs)) * 100.0, 2))

        unit_pct_map[uid] = round(sum(comp_pcts) / total_comp, 2)

    results = {}
    for sid in subj_ids:
        u_list = subj_acc_units.get(sid, [])
        if not u_list:
            results[sid] = 0.0
        else:
            pcts = [unit_pct_map.get(str(u.id), 0.0) for u in u_list]
            results[sid] = round(sum(pcts) / len(u_list), 2)

    return results


def get_progress_overview(user, enrollment):
    """
    Returns an optimized overview dict using bulk calculation.
    """
    if not user or not enrollment:
        return {
            "overall_completion_percentage": 0.0,
            "accessible_completion_percentage": 0.0,
            "subjects_count": 0,
            "completed_subjects": 0,
            "total_learning_seconds": 0,
            "active_study_enrollment": str(enrollment.id) if enrollment else None,
        }

    context = AccessContext.build(user=user, enrollment=enrollment)

    subjects_progress = list(
        SubjectProgress.objects.filter(
            user=user, study_enrollment=enrollment
        ).select_related("subject")
    )
    
    if not subjects_progress:
        return {
            "overall_completion_percentage": 0.0,
            "accessible_completion_percentage": 0.0,
            "subjects_count": 0,
            "completed_subjects": 0,
            "total_learning_seconds": 0,
            "active_study_enrollment": str(enrollment.id),
        }

    subjects = [sp.subject for sp in subjects_progress]
    acc_map = calculate_accessible_completion_for_subjects(user, enrollment, subjects, context=context)

    total_sp = 0
    total_full_pct = 0.0
    total_acc_pct = 0.0
    completed = 0
    time = 0

    for sp in subjects_progress:
        total_sp += 1
        total_full_pct += float(sp.completion_percentage)
        total_acc_pct += acc_map.get(str(sp.subject_id), 0.0)
        time += sp.time_spent_seconds
        if sp.status == "completed" or sp.completion_percentage >= 100:
            completed += 1

    overall_completion = round(total_full_pct / total_sp, 2) if total_sp > 0 else 0.0
    overall_accessible = round(total_acc_pct / total_sp, 2) if total_sp > 0 else 0.0

    return {
        "overall_completion_percentage": overall_completion,
        "accessible_completion_percentage": overall_accessible,
        "subjects_count": total_sp,
        "completed_subjects": completed,
        "total_learning_seconds": time,
        "active_study_enrollment": str(enrollment.id),
    }

