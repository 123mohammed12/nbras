from django.db import migrations
from django.utils import timezone


def archive_unsupported_legacy_questions(apps, schema_editor):
    Question = apps.get_model('question_bank', 'Question')
    Question.objects.exclude(
        question_type__in=['multiple_choice', 'true_false']
    ).filter(status='published').update(
        status='archived', retired_at=timezone.now()
    )


class Migration(migrations.Migration):
    dependencies = [
        ('question_bank', '0007_ar10_question_bank_roles'),
    ]

    operations = [
        migrations.RunPython(archive_unsupported_legacy_questions, migrations.RunPython.noop),
    ]
