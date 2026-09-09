from django.db import migrations, models
import django.db.models.deletion


def backfill_ministerial_occurrences(apps, schema_editor):
    AttemptQuestion = apps.get_model("attempts", "AttemptQuestion")
    rows = AttemptQuestion.objects.filter(
        ministerial_exam_item__isnull=True,
        assessment_item__ministerial_exam_item__isnull=False,
    ).values_list("id", "assessment_item__ministerial_exam_item_id")
    for row_id, occurrence_id in rows.iterator(chunk_size=500):
        AttemptQuestion.objects.filter(id=row_id).update(
            ministerial_exam_item_id=occurrence_id
        )


class Migration(migrations.Migration):
    dependencies = [
        ("attempts", "0005_assessmentattempt_source_scope"),
        ("curriculum", "0001_initial"),
        ("ministerial_exams", "0003_ministerialexam_assessment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assessmentattempt",
            name="assessment",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="attempts", to="assessments.assessment",
            ),
        ),
        migrations.AddField(
            model_name="assessmentattempt", name="dynamic_assessment_type",
            field=models.CharField(blank=True, db_index=True, default="", max_length=30),
        ),
        migrations.AddField(
            model_name="assessmentattempt", name="dynamic_title",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="assessmentattempt", name="selection_spec_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="assessmentattempt", name="selection_policy_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="assessmentattempt", name="dynamic_subject",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="dynamic_assessment_attempts", to="curriculum.subject",
            ),
        ),
        migrations.AddField(
            model_name="attemptquestion", name="ministerial_exam_item",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="attempt_questions", to="ministerial_exams.ministerialexamitem",
            ),
        ),
        migrations.RunPython(backfill_ministerial_occurrences, migrations.RunPython.noop),
    ]
