from django.db import migrations, models


def normalize_scoped_term_ids(apps, schema_editor):
    Term = apps.get_model("curriculum", "Term")
    Unit = apps.get_model("curriculum", "Unit")
    MinisterialExam = apps.get_model("ministerial_exams", "MinisterialExam")

    # Snapshot before creating targets so newly-created terms are not processed.
    source_terms = list(Term.objects.all())
    for source in source_terms:
        contexts = set(
            Unit.objects.filter(term_id=source.pk).values_list(
                "subject__grade_id", "subject__section_id"
            )
        )
        contexts.update(
            MinisterialExam.objects.filter(term_id=source.pk).values_list(
                "subject__grade_id", "subject__section_id"
            )
        )

        for grade_id, section_id in contexts:
            prefix = f"{section_id}_"
            target_id = source.pk if str(source.pk).startswith(prefix) else f"{prefix}{source.pk}"
            target, _ = Term.objects.get_or_create(
                pk=target_id,
                defaults={
                    "grade_id": grade_id,
                    "section_id": section_id,
                    "name_ar": source.name_ar,
                    "sort_order": source.sort_order,
                    "is_active": source.is_active,
                },
            )
            if target.grade_id != grade_id or target.section_id != section_id:
                raise RuntimeError(f"Conflicting scoped term id: {target_id}")

            Unit.objects.filter(
                term_id=source.pk,
                subject__grade_id=grade_id,
                subject__section_id=section_id,
            ).update(term_id=target_id)
            MinisterialExam.objects.filter(
                term_id=source.pk,
                subject__grade_id=grade_id,
                subject__section_id=section_id,
            ).update(term_id=target_id)

        if not Unit.objects.filter(term_id=source.pk).exists() and not MinisterialExam.objects.filter(term_id=source.pk).exists():
            source.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("curriculum", "0003_alter_unit_term"),
        ("ministerial_exams", "0003_ministerialexam_assessment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="term",
            name="id",
            field=models.CharField(
                help_text="مثال: 3s_sci_fy أو 9th_sci_t1",
                max_length=120,
                primary_key=True,
                serialize=False,
            ),
        ),
        migrations.RunPython(normalize_scoped_term_ids, migrations.RunPython.noop),
    ]
