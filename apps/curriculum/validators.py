"""
Curriculum Validation Logic.
"""

from apps.curriculum.exceptions import InvalidGradeSectionError
from apps.curriculum.models import Grade, Section


def validate_and_get_grade_section(grade_id: str, section_id: str | None = None) -> tuple[Grade, Section]:
    """
    Validate Grade and Section combination according to system rules:

    1. Grade must exist and be active.
    2. If section_id is provided: validate it belongs to Grade and is active.
    3. If section_id is NOT provided:
       - If Grade has EXACTLY 1 active Section (e.g. Grade 9 General), auto-select it.
       - If Grade has MULTIPLE active Sections (e.g. Grade 12 Scientific & Literary), raise InvalidGradeSectionError.
       - If Grade has 0 active Sections, raise InvalidGradeSectionError.
    """
    grade = Grade.objects.filter(id=grade_id, is_active=True).first()
    if not grade:
        raise InvalidGradeSectionError(f"الصف الدراسي '{grade_id}' غير موجود أو غير نشط.")

    if section_id:
        section = Section.objects.filter(id=section_id, grade=grade, is_active=True).first()
        if not section:
            raise InvalidGradeSectionError(
                f"القسم '{section_id}' غير صالح أو لا ينتمي للصف '{grade.name_ar}'."
            )
        return grade, section

    # Automatic selection rule
    sections = list(Section.objects.filter(grade=grade, is_active=True))
    if len(sections) == 1:
        return grade, sections[0]
    elif len(sections) > 1:
        raise InvalidGradeSectionError(
            f"الصف '{grade.name_ar}' يحتوي على أكثر من قسم (مسار). يرجى تحديد القسم المطلوب."
        )
    else:
        raise InvalidGradeSectionError(f"لا يوجد أي قسم دراسي نشط متاح للصف '{grade.name_ar}'.")
