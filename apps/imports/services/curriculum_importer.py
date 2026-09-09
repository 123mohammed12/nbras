import json
from pathlib import Path
from django.db import transaction
from apps.curriculum.models import Grade, Section, Subject, Term, Unit, Lesson
from apps.curriculum.models.term import build_scoped_term_id


def import_curriculum_json_file(file_path: str | Path) -> dict:
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
    raw_term_id = data.get("term_id")
    term_id = build_scoped_term_id(section_id=track_id, term_id=raw_term_id)
    term_name = data.get("term_name", raw_term_id)

    with transaction.atomic():
        grade, _ = Grade.objects.update_or_create(
            id=grade_id,
            defaults={"name_ar": grade_name, "sort_order": 1},
        )

        section, _ = Section.objects.update_or_create(
            id=track_id,
            defaults={"grade": grade, "name_ar": track_name, "sort_order": 1},
        )

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

        term, _ = Term.objects.update_or_create(
            id=term_id,
            defaults={
                "grade": grade,
                "section": section,
                "name_ar": term_name,
                "sort_order": 1,
            },
        )

        units_count = 0
        lessons_count = 0

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
            "subject": subject_id,
            "units_imported": units_count,
            "lessons_imported": lessons_count,
        }
