import json
from pathlib import Path
from django.db import transaction
from apps.curriculum.models import Grade, Section, Subject, Term, Unit, Lesson
from apps.curriculum.models.term import build_scoped_term_id


def resolve_grade(grade_id: str, grade_name: str) -> Grade:
    """البحث عن الصف الدراسي الموجود مسبقاً أو إنشاؤه في حال عدم وجوده."""
    # 1. البحث عبر المعرف
    if grade_id:
        grade = Grade.objects.filter(id=grade_id).first()
        if grade:
            return grade

    # 2. البحث عبر الاسم العربي
    if grade_name:
        clean_name = grade_name.strip()
        grade = Grade.objects.filter(name_ar__icontains=clean_name).first()
        if grade:
            return grade

    # 3. إنشاء كخيار أخير
    grade, _ = Grade.objects.get_or_create(
        id=grade_id,
        defaults={"name_ar": grade_name or grade_id, "sort_order": 1},
    )
    return grade


def resolve_section(grade: Grade, track_id: str, track_name: str) -> Section:
    """البحث عن القسم/المسار الموجود مسبقاً التابع للصف أو إنشاؤه."""
    # 1. البحث عبر المعرف
    if track_id:
        section = Section.objects.filter(id=track_id).first()
        if section:
            return section

    # 2. البحث عبر الاسم ضمن الصف
    if track_name:
        clean_name = track_name.strip()
        section = Section.objects.filter(grade=grade, name_ar__icontains=clean_name).first()
        if section:
            return section

    # 3. إنشاء كخيار أخير
    section, _ = Section.objects.get_or_create(
        id=track_id,
        defaults={"grade": grade, "name_ar": track_name or track_id, "sort_order": 1},
    )
    return section


def resolve_term(grade: Grade, section: Section, term_id: str, term_name: str) -> Term:
    """البحث عن الترم/الفصل الدراسي الموجود مسبقاً مع مطابقة ذكية للقسم والصف."""
    # 1. البحث بالمعرف المباشر
    if term_id:
        term = Term.objects.filter(id=term_id).first()
        if term:
            return term

    # 2. المعرف المركب مع المسار
    scoped_id = build_scoped_term_id(section_id=section.id, term_id=term_id) if (section and term_id) else None
    if scoped_id:
        term = Term.objects.filter(id=scoped_id).first()
        if term:
            return term

    # 3. البحث بالاسم ضمن المسار
    if term_name:
        clean_name = term_name.strip()
        term = Term.objects.filter(section=section, name_ar__icontains=clean_name).first()
        if term:
            return term

    # 4. مطابقة الكلمات الدلالية (عام كامل / ترم أول / ترم ثاني)
    t_clean = (term_name or "").strip()
    t_id_lower = (term_id or "").lower()

    if "كامل" in t_clean or "عام" in t_clean or "fy" in t_id_lower:
        term = (
            Term.objects.filter(section=section, name_ar__icontains="كامل").first()
            or Term.objects.filter(section=section, name_ar__icontains="عام").first()
            or Term.objects.filter(section=section, id__icontains="fy").first()
        )
        if term:
            return term
    elif "أول" in t_clean or "1" in t_clean or "t1" in t_id_lower:
        term = (
            Term.objects.filter(section=section, name_ar__icontains="أول").first()
            or Term.objects.filter(section=section, id__icontains="t1").first()
        )
        if term:
            return term
    elif "ثان" in t_clean or "2" in t_clean or "t2" in t_id_lower:
        term = (
            Term.objects.filter(section=section, name_ar__icontains="ثان").first()
            or Term.objects.filter(section=section, id__icontains="t2").first()
        )
        if term:
            return term

    # 5. إذا كان للمسار ترم واحد فقط مسجل، نستخدمه
    existing_terms = Term.objects.filter(section=section)
    if existing_terms.count() == 1:
        return existing_terms.first()

    # 6. إنشاء الترم في حال عدم وجوده مطلقاً لضمان عدم توقف الاستيراد
    target_id = scoped_id or term_id
    term, _ = Term.objects.get_or_create(
        id=target_id,
        defaults={
            "grade": grade,
            "section": section,
            "name_ar": term_name or term_id,
            "sort_order": 1,
        },
    )
    return term


def import_curriculum_json_file(file_path: str | Path) -> dict:
    """
    استيراد محتويات المنهج (المواد، الوحدات، الدروس) من ملف JSON
    مع ربطها تلقائياً وبالدقة العالية بالصفوف والأقسام والاترام الموجودة مسبقاً.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    grade_id = data.get("grade_id")
    grade_name = data.get("grade_name", grade_id)
    track_id = data.get("track_id")
    track_name = data.get("track_name", track_id)
    subject_id = data.get("subject_id")
    subject_name = data.get("subject_name", subject_id)
    term_id = data.get("term_id")
    term_name = data.get("term_name", term_id)

    with transaction.atomic():
        # 1. مطابقة الصف والقسم والترم الموجودين مسبقاً
        grade = resolve_grade(grade_id, grade_name)
        section = resolve_section(grade, track_id, track_name)
        term = resolve_term(grade, section, term_id, term_name)

        # 2. إنشاء / تحديث المادة الدراسية وربطها بالصف والقسم
        subject, _ = Subject.objects.update_or_create(
            id=subject_id,
            defaults={
                "grade": grade,
                "section": section,
                "name_ar": subject_name,
                "sort_order": 1,
                "status": "published",
            },
        )

        units_count = 0
        lessons_count = 0

        # 3. إنشاء / تحديث الوحدات الدراسية وربطها بالمادة والترم
        for u_data in data.get("units", []):
            unit_id = u_data.get("id")
            unit_title = u_data.get("name", unit_id)
            unit_order = u_data.get("order_index", 1)

            unit, _ = Unit.objects.update_or_create(
                id=unit_id,
                defaults={
                    "subject": subject,
                    "term": term,
                    "title": unit_title,
                    "sort_order": unit_order,
                    "status": "published",
                },
            )
            units_count += 1

            # 4. إنشاء / تحديث الدروس وربطها بالوحدة
            for l_data in u_data.get("lessons", []):
                lesson_id = l_data.get("id")
                lesson_title = l_data.get("name", lesson_id)
                lesson_order = l_data.get("order_index", 1)

                Lesson.objects.update_or_create(
                    id=lesson_id,
                    defaults={
                        "unit": unit,
                        "title": lesson_title,
                        "sort_order": lesson_order,
                        "status": "published",
                    },
                )
                lessons_count += 1

        return {
            "file": path.name,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "grade": grade.name_ar,
            "section": section.name_ar,
            "term": term.name_ar,
            "units_imported": units_count,
            "lessons_imported": lessons_count,
        }
