from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("curriculum", "0004_normalize_scoped_term_ids"),
        ("progress", "0003_smart_card_sessions"),
    ]

    operations = [
        migrations.CreateModel(
            name="MasteryAggregate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope_type", models.CharField(choices=[("subject", "Subject"), ("unit", "Unit"), ("lesson", "Lesson")], max_length=12)),
                ("scope_id", models.CharField(max_length=64)),
                ("mastery_score", models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True)),
                ("distinct_evidence_count", models.PositiveIntegerField(default=0)),
                ("effective_evidence", models.DecimalField(decimal_places=4, default=0, max_digits=10)),
                ("confidence", models.CharField(default="insufficient", max_length=20)),
                ("trend", models.CharField(default="insufficient_data", max_length=20)),
                ("weakness_status", models.CharField(default="unknown", max_length=30)),
                ("weakness_priority", models.CharField(blank=True, default="", max_length=20)),
                ("weakness_reason", models.CharField(blank=True, default="", max_length=120)),
                ("source_breakdown", models.JSONField(blank=True, default=dict)),
                ("difficulty_breakdown", models.JSONField(blank=True, default=dict)),
                ("question_type_breakdown", models.JSONField(blank=True, default=dict)),
                ("policy_version", models.CharField(max_length=30)),
                ("calculated_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("study_enrollment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mastery_aggregates", to="curriculum.studyenrollment")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mastery_aggregates", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "progress_mastery_aggregates"},
        ),
        migrations.AddConstraint(
            model_name="masteryaggregate",
            constraint=models.UniqueConstraint(fields=("user", "study_enrollment", "scope_type", "scope_id"), name="unique_mastery_scope_per_enrollment"),
        ),
        migrations.AddIndex(
            model_name="masteryaggregate",
            index=models.Index(fields=["user", "study_enrollment", "scope_type"], name="progress_mastery_scope_idx"),
        ),
    ]
