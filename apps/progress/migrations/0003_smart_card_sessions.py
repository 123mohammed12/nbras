import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0002_lessonexplanation_and_more"),
        ("progress", "0002_attemptprogressreceipt_learningresourceprogress_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningsession",
            name="current_position",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="learningsession",
            name="session_state",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="learningsession",
            name="total_items",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="SmartCardReview",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("rating", models.CharField(choices=[("again", "تحتاج مراجعة"), ("hard", "بصعوبة"), ("good", "عرفتها")], max_length=20)),
                ("client_event_id", models.CharField(max_length=255)),
                ("reviewed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("card", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reviews", to="content.flashcard")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="smart_card_reviews", to="progress.learningsession")),
            ],
            options={
                "verbose_name": "مراجعة بطاقة ذكية",
                "verbose_name_plural": "مراجعات البطاقات الذكية",
                "db_table": "progress_smart_card_reviews",
                "ordering": ["reviewed_at", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="smartcardreview",
            constraint=models.UniqueConstraint(fields=("session", "client_event_id"), name="unique_smart_card_review_event_per_session"),
        ),
        migrations.AddConstraint(
            model_name="smartcardreview",
            constraint=models.UniqueConstraint(fields=("session", "card"), name="unique_smart_card_review_per_session_card"),
        ),
    ]
