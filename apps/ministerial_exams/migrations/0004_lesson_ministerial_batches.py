import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0004_normalize_scoped_term_ids"),
        ("ministerial_exams", "0003_ministerialexam_assessment"),
    ]

    operations = [
        migrations.CreateModel(
            name="LessonMinisterialBatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("batch_index", models.PositiveIntegerField()),
                ("target_size", models.PositiveIntegerField(default=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("lesson", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ministerial_batches", to="curriculum.lesson")),
            ],
            options={"db_table": "lesson_ministerial_batches", "ordering": ["batch_index"]},
        ),
        migrations.CreateModel(
            name="LessonMinisterialBatchItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sort_order", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="batch_items", to="ministerial_exams.lessonministerialbatch")),
                ("ministerial_exam_item", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="lesson_batch_item", to="ministerial_exams.ministerialexamitem")),
            ],
            options={"db_table": "lesson_ministerial_batch_items", "ordering": ["sort_order"]},
        ),
        migrations.AddConstraint(
            model_name="lessonministerialbatch",
            constraint=models.UniqueConstraint(fields=("lesson", "batch_index"), name="unique_lesson_ministerial_batch_index"),
        ),
        migrations.AddConstraint(
            model_name="lessonministerialbatchitem",
            constraint=models.UniqueConstraint(fields=("batch", "sort_order"), name="unique_lesson_ministerial_batch_item_order"),
        ),
    ]
