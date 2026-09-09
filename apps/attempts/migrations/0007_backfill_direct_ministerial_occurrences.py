from django.db import migrations


def backfill_snapshot_occurrences(apps, schema_editor):
    AttemptQuestion = apps.get_model("attempts", "AttemptQuestion")
    MinisterialExamItem = apps.get_model("ministerial_exams", "MinisterialExamItem")
    rows = AttemptQuestion.objects.filter(
        ministerial_exam_item__isnull=True,
        source_type="ministerial",
    ).values_list("id", "source_metadata_snapshot")
    candidates = []
    for row_id, snapshot in rows.iterator(chunk_size=500):
        occurrence_id = (snapshot or {}).get("ministerial_exam_item_id")
        if occurrence_id:
            candidates.append((row_id, occurrence_id))
    valid = {
        str(value) for value in MinisterialExamItem.objects.filter(
            id__in=[value for _, value in candidates]
        ).values_list("id", flat=True)
    }
    for row_id, occurrence_id in candidates:
        if str(occurrence_id) in valid:
            AttemptQuestion.objects.filter(id=row_id).update(
                ministerial_exam_item_id=occurrence_id
            )


class Migration(migrations.Migration):
    dependencies = [
        ("attempts", "0006_dynamic_custom_attempts"),
        ("ministerial_exams", "0004_lesson_ministerial_batches"),
    ]

    operations = [
        migrations.RunPython(backfill_snapshot_occurrences, migrations.RunPython.noop),
    ]
