from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("question_bank", "0003_questionasset_unique_question_asset_order_and_more")]

    operations = [
        migrations.AddField(
            model_name="questionversion",
            name="answer_key",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="الإجابة المرجعية كما وردت من المصدر؛ لا تُعرض للطالب قبل التصحيح.",
            ),
        ),
    ]
