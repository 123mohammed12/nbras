from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attempts", "0004_assessmentattempt_auto_submit_on_expiry_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentattempt",
            name="source_scope",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
