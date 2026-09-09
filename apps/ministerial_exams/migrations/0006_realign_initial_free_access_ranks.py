from django.db import migrations


def realign_initial_ranks(apps, schema_editor):
    Exam = apps.get_model("ministerial_exams", "MinisterialExam")
    # This is a one-time assignment matching the existing learner catalog
    # order. Future inserts do not trigger re-ranking and therefore cannot
    # silently change which models are free.
    Exam.objects.update(free_access_rank=None)
    subject_ids = Exam.objects.values_list("subject_id", flat=True).distinct()
    for subject_id in subject_ids:
        rows = list(
            Exam.objects.filter(subject_id=subject_id).order_by(
                "-exam_year", "model_number", "created_at", "id"
            )
        )
        for rank, exam in enumerate(rows, 1):
            exam.free_access_rank = rank
        Exam.objects.bulk_update(rows, ["free_access_rank"])


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("ministerial_exams", "0005_ministerialexam_free_access_rank_and_more"),
    ]

    operations = [
        migrations.RunPython(realign_initial_ranks, migrations.RunPython.noop),
    ]
