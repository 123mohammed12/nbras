from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attempts", "0008_question_performance_evidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentattempt",
            name="revision",
            field=models.PositiveBigIntegerField(default=0),
        ),
    ]
