import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assessments", "0005_trainingbatch_trainingbatchitem_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentblueprint",
            name="key",
            field=models.SlugField(blank=True, max_length=120, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="assessmentblueprint",
            name="title",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="assessmentblueprint",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="assessmentblueprint",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "مسودة"),
                    ("under_review", "قيد المراجعة"),
                    ("approved", "معتمد"),
                    ("published", "منشور"),
                    ("archived", "مؤرشف"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="assessmentblueprint",
            name="assessment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="blueprints",
                to="assessments.assessment",
            ),
        ),
        migrations.AlterField(
            model_name="assessment",
            name="assessment_type",
            field=models.CharField(
                choices=[
                    ("ministerial_exam", "نموذج وزاري كامل"),
                    ("lesson_test", "اختبار درس"),
                    ("unit_test", "اختبار وحدة"),
                    ("subject_test", "اختبار مادة (محدود)"),
                    ("self_practice", "اختبر نفسك"),
                    ("custom_test", "اختبار مخصص"),
                    ("mock_exam", "اختبار محاكاة"),
                    ("training_test", "اختبار تدريبي"),
                    ("wrong_answers_test", "إعادة الأسئلة الخاطئة"),
                    ("unanswered_test", "إعادة الأسئلة غير المجابة"),
                    ("monthly_test", "اختبار شهري"),
                    ("group_test", "اختبار مجموعات"),
                    ("ai_generated_test", "اختبار مصنع بالذكاء الاصطناعي"),
                    ("lesson_ministerial", "Lesson ministerial practice"),
                ],
                db_index=True,
                default="lesson_test",
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="AssessmentBlueprintVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version_number", models.PositiveIntegerField(default=1)),
                ("title", models.CharField(max_length=255)),
                ("status", models.CharField(choices=[("draft", "مسودة"), ("under_review", "قيد المراجعة"), ("approved", "معتمد"), ("published", "منشور"), ("archived", "مؤرشف")], db_index=True, default="draft", max_length=20)),
                ("question_count", models.PositiveIntegerField()),
                ("duration_minutes", models.PositiveIntegerField()),
                ("total_points", models.DecimalField(decimal_places=2, max_digits=6)),
                ("source_types", models.JSONField(default=list)),
                ("years", models.JSONField(blank=True, default=list)),
                ("scope", models.JSONField(default=dict)),
                ("unit_distribution", models.JSONField(default=dict)),
                ("difficulty_distribution", models.JSONField(default=dict)),
                ("question_type_distribution", models.JSONField(default=dict)),
                ("selection_buckets", models.JSONField(default=list)),
                ("selection_policy_version", models.PositiveIntegerField(default=2)),
                ("is_current", models.BooleanField(default=False)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("blueprint", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="assessments.assessmentblueprint")),
            ],
            options={"db_table": "assessment_blueprint_versions", "ordering": ["-version_number"]},
        ),
        migrations.AddConstraint(
            model_name="assessmentblueprintversion",
            constraint=models.UniqueConstraint(fields=("blueprint", "version_number"), name="unique_blueprint_version_number"),
        ),
        migrations.AddConstraint(
            model_name="assessmentblueprintversion",
            constraint=models.UniqueConstraint(condition=models.Q(("is_current", True)), fields=("blueprint",), name="unique_current_blueprint_version"),
        ),
    ]
